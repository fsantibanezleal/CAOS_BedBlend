"""The incoming stream, generated from a DIG SEQUENCE rather than from a variogram knob.

THIS IS A CORRECTION, NOT A REFACTOR. The previous version took ``range_t``, the practical range of
the grade covariance in tonnes, as an input parameter. That is backwards. The autocorrelation of the
material arriving at a stockpile is not a property anyone sets; it is a consequence of how the pit is
being dug:

    "When data are collected from a single grade block, the material transported to dump locations
    are spatially correlated."

Consecutive trucks load from the same dig block, so consecutive loads carry similar grades, and the
correlation length of the stream is set by how long a shovel dwells in one block before moving. An
industrial simulation models it exactly this way: the deposit is mined sequentially by pushback and by
pit, top bench first and then one bench down, with two adjacent blocks loaded into each truck
(Neufeld, Lyall and Deutsch, CCG Report 8 paper 306, 2006).

So this module takes what an operation actually controls, the block layout and the shovel schedule,
and the correlation falls out. ``measured_range_t`` then REPORTS the range the generated stream
actually has, which is the honest direction of that relationship.

THE GRADE ON A LOAD IS ALREADY UNCERTAIN before the truck moves. Ore-control misclassification from
sampling error alone runs 5 to 20 percent for base and precious metal mines, with a further 9 to 19
percent ore loss from blast movement and dilution (Minerals 2021, 11, 636, section 1.6). Every payload
carries that uncertainty rather than presenting a crisp number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .truck import Payload


class Xorshift:
    """A seeded xorshift32, reproducible bit for bit against a browser implementation.

    Deliberately not ``random``: the live engine has to produce the identical sequence, and a
    language's built-in generator is not a portable contract.
    """

    __slots__ = ("_spare", "state")

    def __init__(self, seed: int) -> None:
        self.state = (seed | 1) & 0xFFFFFFFF
        self._spare: float | None = None

    def uniform(self) -> float:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state / 0x100000000

    def normal(self) -> float:
        """Box-Muller, caching the second deviate so both are used."""
        if self._spare is not None:
            v, self._spare = self._spare, None
            return v
        u1 = max(self.uniform(), 1e-12)
        u2 = self.uniform()
        r = math.sqrt(-2.0 * math.log(u1))
        self._spare = r * math.sin(2.0 * math.pi * u2)
        return r * math.cos(2.0 * math.pi * u2)


@dataclass(frozen=True)
class DigBlock:
    """One ore-control block: a grade, and how many loads come out of it.

    Block grades are drawn once and then every load from that block sits near it. That is the whole
    mechanism: the block is the correlated unit, and the shovel's dwell in it is the correlation
    length expressed in tonnes.
    """

    index: int
    grade: float
    n_loads: int
    bench: int = 0


@dataclass(frozen=True)
class DigSequence:
    """The schedule the shovel works: which blocks, in what order, for how long each.

    ``blocks`` are consumed in order. Reordering them changes the stream's structure without changing
    a single grade, which is the point: the sequence IS the control.
    """

    blocks: list[DigBlock]

    @property
    def n_loads(self) -> int:
        return sum(b.n_loads for b in self.blocks)


def dig_sequence(
    *,
    n_loads: int,
    seed: int,
    loads_per_block: int = 20,
    mean_grade: float = 0.62,
    block_sd: float = 0.16,
    bench_trend: float = 0.0,
    n_benches: int = 1,
) -> DigSequence:
    """Build a dig schedule.

    ``loads_per_block`` is the shovel's dwell, and it is the parameter that sets the stream's
    correlation length. A short dwell means the stream decorrelates quickly and the pile has
    independent material to average; a long dwell means whole layers share a grade and the bed can
    barely help. That is the honest version of what the old ``range_t`` knob was pretending to be.

    ``bench_trend`` adds a grade drift between benches, which is what makes a deposit's upper and
    lower benches systematically different and is a real reason a stockpile's own lifts differ.
    """
    rng = Xorshift(seed)
    n_blocks = max(1, math.ceil(n_loads / max(1, loads_per_block)))
    blocks: list[DigBlock] = []
    placed = 0
    k = 0
    while placed < n_loads:
        take = min(loads_per_block, n_loads - placed)
        bench = (k * n_benches) // n_blocks
        grade = mean_grade + block_sd * rng.normal() + bench_trend * bench
        blocks.append(DigBlock(index=k, grade=max(grade, 0.0), n_loads=take, bench=bench))
        placed += take
        k += 1
    return DigSequence(blocks=blocks)


def payloads_from(
    seq: DigSequence,
    *,
    seed: int,
    tonnes_per_truck: float = 231.0,
    truck_spread: float = 0.06,
    within_block_sd: float = 0.02,
    grade_uncertainty: float = 0.12,
) -> list[Payload]:
    """Turn a dig schedule into the ordered stream of loads that arrives at the stockpile.

    ``within_block_sd`` is the residual variation inside a block, which is small by construction: a
    block is the unit the ore-control model calls uniform, and if loads inside one varied as much as
    loads between blocks there would be no correlation to speak of.

    ``grade_uncertainty`` is the published ore-control misclassification carried onto every load. It
    defaults to 12 percent, the middle of the reported 5 to 20 percent band.
    """
    rng = Xorshift(seed ^ 0x5EED)
    out: list[Payload] = []
    for b in seq.blocks:
        for _ in range(b.n_loads):
            out.append(
                Payload(
                    tonnes=tonnes_per_truck * (1.0 + truck_spread * rng.normal()),
                    grade=max(b.grade + within_block_sd * rng.normal(), 0.0),
                    source_block=b.index,
                    grade_uncertainty=grade_uncertainty,
                )
            )
    return out


def measured_range_t(payloads: list[Payload], *, n_lags: int = 30) -> float:
    """The practical range of the stream that was actually generated, in tonnes.

    REPORTED, NOT SET. This is the number the old engine took as an input. Estimating it from the
    stream closes the loop: a reader changes the shovel dwell, sees the range move, and sees the
    variance reduction move with it, which is a causal story rather than two knobs that happen to
    agree.

    Practical range is the lag at which the experimental semivariogram first reaches 95 percent of
    the series variance, linearly interpolated between lags, expressed in tonnes.
    """
    n = len(payloads)
    if n < 4:
        return 0.0
    g = [p.grade for p in payloads]
    mean = sum(g) / n
    var = sum((v - mean) ** 2 for v in g) / n
    if var <= 0:
        return 0.0

    t_per = sum(p.tonnes for p in payloads) / n
    max_lag = min(n_lags, n // 2)
    prev_lag, prev_gam = 0, 0.0
    for lag in range(1, max_lag + 1):
        pairs = n - lag
        gam = sum((g[i] - g[i + lag]) ** 2 for i in range(pairs)) / (2.0 * pairs)
        if gam >= 0.95 * var:
            span = gam - prev_gam
            frac = (0.95 * var - prev_gam) / span if span > 0 else 0.0
            return (prev_lag + frac * (lag - prev_lag)) * t_per
        prev_lag, prev_gam = lag, gam
    return max_lag * t_per


def cumulative_tonnes(payloads: list[Payload]) -> list[float]:
    """Running tonnage, the natural x-axis for anything plotted along the stream."""
    out: list[float] = []
    run = 0.0
    for p in payloads:
        run += p.tonnes
        out.append(run)
    return out
