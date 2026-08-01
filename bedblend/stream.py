"""The incoming truck stream: a geostatistically structured grade sequence, not white noise.

WHY THIS IS NOT A RANDOM NUMBER GENERATOR WITH A MEAN. The whole question a blending bed answers is
how much of the input's variability survives. That answer depends on the input's AUTOCORRELATION, not
just its variance: if consecutive trucks are strongly correlated, the layers a reclaim cut crosses are
not independent samples and the bed recovers far less than the ``1/N`` bound promises. A white-noise
input would make every bed look excellent and would hide the single most important effect in the
domain.

Marques and Costa, Int. J. Miner. Process. 120, 48-55, 2013, doi:10.1016/j.minpro.2013.01.003, make
exactly this point: they drive their blending-pile simulator with geostatistically simulated grades so
that in-situ variability, not noise, reaches the pile, and they validate it on two large Vale iron
mines. This module is the live-lane counterpart of that approach.

THE MODEL. A stationary Gaussian process in cumulative tonnage with an exponential covariance

    C(h) = sill * exp(-3 h / a)

which has the practical range ``a`` at which the correlation has fallen to about 5 percent, the
standard geostatistical convention. On evenly spaced samples this process has an exact one-step
recursion,

    z[k+1] = rho z[k] + sqrt(1 - rho^2) e[k],      rho = exp(-3 dh / a)

so it is generated exactly rather than approximately, in one pass, with no matrix factorisation. That
matters because the same generator has to run in the browser and produce results identical to the
offline lane.

The offline pipeline additionally offers sequential Gaussian simulation over a real three-dimensional
ore body through GSTools (Muller, Schuler, Zech and Hesse, Geosci. Model Dev. 15, 3161-3182, 2022,
doi:10.5194/gmd-15-3161-2022) and real published block models through MineLib. Those are richer, and
they are what the controlled and real cases use; this exponential process is the live lane's exact,
cheap, honestly-labelled equivalent.
"""
from __future__ import annotations

import math

from .schema import TruckDump

STRUCTURES: tuple[str, ...] = ("stationary", "short_range", "long_range", "trending", "bimodal")


class _Gauss:
    """A seeded normal generator, reproduced identically in the TypeScript live lane.

    A 32-bit xorshift feeding a Box-Muller transform. Python's ``random`` and numpy's Generator are
    both excellent and neither can be reproduced bit for bit in a browser, and the cross-lane
    determinism test requires that they can. So the generator is written out, once, in a form both
    languages express the same way.
    """

    __slots__ = ("_s", "_spare")

    def __init__(self, seed: int) -> None:
        self._s = (int(seed) & 0xFFFFFFFF) or 0x9E3779B9
        self._spare: float | None = None

    def _u32(self) -> int:
        x = self._s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self._s = x & 0xFFFFFFFF
        return self._s

    def uniform(self) -> float:
        return (self._u32() + 0.5) / 4294967296.0

    def normal(self) -> float:
        if self._spare is not None:
            v, self._spare = self._spare, None
            return v
        u1 = max(1e-12, self.uniform())
        u2 = self.uniform()
        r = math.sqrt(-2.0 * math.log(u1))
        self._spare = r * math.sin(2.0 * math.pi * u2)
        return r * math.cos(2.0 * math.pi * u2)


def generate_stream(
    *,
    n_dumps: int,
    seed: int,
    structure: str = "stationary",
    mean_cu: float = 0.62,
    sd_cu: float = 0.16,
    range_t: float = 4000.0,
    tonnes_per_truck: float = 220.0,
    truck_spread: float = 0.06,
    coarse_mean: float = 0.35,
    coarse_sd: float = 0.08,
    cycle_s: float = 90.0,
) -> list[TruckDump]:
    """Generate ``n_dumps`` truck loads with a realistic grade structure.

    ``range_t`` is the practical range of the grade covariance IN TONNES along the stream. Comparing
    it against the tonnage laid down per stacker pass is what decides whether a bed can help at all,
    and it is the parameter the V01 and V02 cases sweep between "much shorter than a layer" and
    "longer than the whole pile".

    The five structures are the input-variability axis of the case matrix:

    * ``stationary``  a plain correlated stream at the stated range
    * ``short_range`` range much shorter than one layer, so layers are nearly independent and the
                      achieved VRR should approach the ``1/N`` bound
    * ``long_range``  range longer than the pile, so the bed barely helps; this case ships as a
                      headline rather than being buried, because it is the honest one
    * ``trending``    a linear drift across the shift on top of the correlated field; the mean moves
                      and variance reduction becomes a misleading summary
    * ``bimodal``     two ore types, so the reclaimed histogram stays bimodal even when the VRR looks
                      good; the distribution has to be shown, not just its second moment
    """
    if structure not in STRUCTURES:
        raise ValueError(f"unknown structure {structure!r}; expected one of {STRUCTURES}")

    g = _Gauss(seed)
    eff_range = range_t
    if structure == "short_range":
        eff_range = max(1.0, range_t * 0.08)
    elif structure == "long_range":
        eff_range = range_t * 12.0

    dumps: list[TruckDump] = []
    cum_t = 0.0
    z = g.normal()
    dh = tonnes_per_truck
    rho = math.exp(-3.0 * dh / eff_range) if eff_range > 0 else 0.0
    root = math.sqrt(max(0.0, 1.0 - rho * rho))

    # a second, independent correlated field drives the size distribution, because size and grade are
    # not the same geological variable; coupling them would bake in a correlation the data does not have
    gs = _Gauss(seed ^ 0x5BF03635)
    zs = gs.normal()

    for k in range(n_dumps):
        t_t = tonnes_per_truck * (1.0 + truck_spread * g.normal())
        t_t = max(20.0, t_t)
        z = rho * z + root * g.normal()
        zs = rho * zs + root * gs.normal()

        cu = mean_cu + sd_cu * z
        if structure == "trending":
            cu += sd_cu * 2.2 * (k / max(1, n_dumps - 1) - 0.5)
        elif structure == "bimodal":
            # two ore types: the correlated field selects which population this truck belongs to, so
            # the modes come in runs, as they would from two dig faces, not interleaved at random
            cu = (mean_cu - 0.9 * sd_cu) if z < 0 else (mean_cu + 0.9 * sd_cu)
            cu += 0.35 * sd_cu * g.normal()
        cu = max(0.0, cu)

        coarse = min(0.95, max(0.05, coarse_mean + coarse_sd * zs))
        au = max(0.0, 0.12 + 0.05 * z)

        dumps.append(TruckDump(
            event_id=k,
            t_s=k * cycle_s,
            truck_id=f"T{(k % 12) + 1:02d}",
            source_id=f"DIG-{(k // 40) + 1:03d}",
            tonnes=t_t,
            grade_cu_pct=cu,
            grade_au_gpt=au,
            coarse_frac=coarse,
            moisture_pct=3.0,
            x_m=0.0, y_m=0.0,          # the stacking geometry assigns the pad position
        ))
        cum_t += t_t

    return dumps


def cumulative_tonnes(dumps: list[TruckDump]) -> list[float]:
    """Cumulative tonnage at each dump, the one-dimensional coordinate the variogram uses."""
    out: list[float] = []
    acc = 0.0
    for d in dumps:
        acc += d.tonnes
        out.append(acc)
    return out
