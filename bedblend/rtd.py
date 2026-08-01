"""Method 12, the residence-time distribution of the stockpile as a buffer.

A stockpile is not only a blender, it is a buffer between the pit and the plant, and its
residence-time distribution is decided entirely by its geometry and its reclaim rule. A freshly built
cone reclaimed from its face behaves close to last-in-first-out; a properly bedded chevron reclaimed
full-face behaves close to a well-mixed first-in-first-out. Neither is exact, and the honest answer is
the SHAPE of the distribution rather than a label.

That three-way FIFO, LIFO and blended abstraction is the industry's own, not ours: mine-planning
software exposes stockpile reclaim as exactly those three rules (Micromine Alastri APS stockpile
documentation). Process-scale RTD in mineral processing is treated in Moraga, Kracht and Ortiz,
Minerals Engineering 187, 107807, 2022, doi:10.1016/j.mineng.2022.107807.

WHAT IS COMPUTED. Each reclaim cut carries the tonnage-weighted mean time its material spent in the
pile. Across all cuts that gives an empirical RTD, from which the mean and the variance follow. The
FIFO and LIFO references are computed for the SAME event sequence, so the pile's actual character is
placed between two curves it could have had rather than asserted to be one of them.
"""
from __future__ import annotations

import math


def histogram(residences_s: list[float], weights_t: list[float], n_bins: int = 24) -> dict:
    """Tonnage-weighted residence-time histogram plus its cumulative curve.

    Weighted by tonnage rather than by cut count, for the same reason the variance is: cuts are not
    all the same size, and an unweighted histogram would let a small cut speak as loudly as a large
    one.
    """
    if not residences_s:
        return {"edges": [], "mass": [], "cumulative": [], "mean_s": 0.0, "var_s2": 0.0}
    lo, hi = min(residences_s), max(residences_s)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / n_bins
    mass = [0.0] * n_bins
    for r, w in zip(residences_s, weights_t, strict=True):
        b = min(n_bins - 1, max(0, int((r - lo) / width)))
        mass[b] += w
    total = sum(mass) or 1.0
    mass = [m / total for m in mass]
    cum: list[float] = []
    acc = 0.0
    for m in mass:
        acc += m
        cum.append(acc)
    tot_w = sum(weights_t) or 1.0
    mean = sum(r * w for r, w in zip(residences_s, weights_t, strict=True)) / tot_w
    var = sum(w * (r - mean) ** 2 for r, w in zip(residences_s, weights_t, strict=True)) / tot_w
    return {
        "edges": [lo + (b + 0.5) * width for b in range(n_bins)],
        "mass": mass,
        "cumulative": cum,
        "mean_s": mean,
        "var_s2": var,
    }


def fifo_lifo_references(
    dump_times_s: list[float],
    dump_tonnes: list[float],
    cut_times_s: list[float],
    cut_tonnes: list[float],
) -> dict:
    """Mean residence time the same event sequence would give under pure FIFO and pure LIFO.

    Both are computed by walking an explicit inventory queue, not by a closed-form approximation, so
    the references are exact for the sequence they describe and remain valid when the stacking and
    reclaim rates are not constant.
    """
    def walk(lifo: bool) -> float:
        stock: list[list[float]] = []  # [time_in, tonnes]
        di = 0
        weighted = 0.0
        total = 0.0
        for ct, need in zip(cut_times_s, cut_tonnes, strict=True):
            while di < len(dump_times_s) and dump_times_s[di] <= ct:
                stock.append([dump_times_s[di], dump_tonnes[di]])
                di += 1
            want = need
            while want > 1e-9 and stock:
                item = stock[-1] if lifo else stock[0]
                take = min(want, item[1])
                weighted += take * (ct - item[0])
                total += take
                item[1] -= take
                want -= take
                if item[1] <= 1e-9:
                    stock.pop() if lifo else stock.pop(0)
        return weighted / total if total > 0 else 0.0

    return {"fifo_mean_s": walk(False), "lifo_mean_s": walk(True)}


def character(actual_mean_s: float, fifo_mean_s: float, lifo_mean_s: float) -> tuple[float, str]:
    """Place the measured mean residence between the LIFO and FIFO references.

    Returns ``(position, label)`` where position is 0 at pure LIFO and 1 at pure FIFO. The label is a
    descriptive band over that position, and the wording in the UI says it is descriptive: there is no
    published threshold that makes 0.6 "mostly first-in-first-out", and pretending otherwise would be
    the kind of invented number the honesty gate forbids.
    """
    span = fifo_mean_s - lifo_mean_s
    if abs(span) < 1e-9:
        return 0.5, "indeterminate"
    p = (actual_mean_s - lifo_mean_s) / span
    p = min(1.0, max(0.0, p))
    if p < 0.25:
        return p, "last-in-first-out"
    if p > 0.75:
        return p, "first-in-first-out"
    return p, "blended"


def theoretical_plug_flow_variance(mean_s: float) -> float:
    """Variance of an ideal plug-flow buffer, which is zero, kept explicit for the comparison panel."""
    return 0.0 * mean_s


def dimensionless_variance(mean_s: float, var_s2: float) -> float:
    """``sigma^2 / tau^2``, the standard dimensionless RTD spread.

    Zero for ideal plug flow, one for an ideal perfectly mixed tank. It places the pile on the
    familiar reactor-engineering scale, which is the scale the process people reading this already
    think in.
    """
    if mean_s <= 0:
        return 0.0
    return var_s2 / (mean_s * mean_s)


def mean_and_sd(residences_s: list[float], weights_t: list[float]) -> tuple[float, float]:
    w = sum(weights_t)
    if w <= 0:
        return 0.0, 0.0
    m = sum(r * t for r, t in zip(residences_s, weights_t, strict=True)) / w
    v = sum(t * (r - m) ** 2 for r, t in zip(residences_s, weights_t, strict=True)) / w
    return m, math.sqrt(max(0.0, v))
