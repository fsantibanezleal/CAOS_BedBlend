"""Methods 9, 10 and 11: the variance reduction ratio, the variogram, and the independent-layer bound.

THE METRIC, AND THE DIRECTION OF THE INEQUALITY.

    VRR = var_out / var_in            LOWER IS BETTER

That is the definition in Loubser and de Korte, J. S. Afr. Inst. Min. Metall. 115(8), 773-780, 2015,
doi:10.17159/2411-9717/2015/v115n8a15, following Kumral (2006), and their own results confirm the
direction: cone shell 0.232, chevcon 0.121, with the text concluding that chevcon "has proven to
deliver much better consistency". The reciprocal convention also circulates in secondary sources, and
building against it would invert every number in the product and make the recommendation layer advise
the worse stacking method. This is why ``vrr_formula_label`` exists and why the product renders the
formula next to the number on every surface.

Both variances must be computed ON THE SAME BASE, that is, over equal tonnages rather than equal
counts. Kumral states the requirement and it is easy to violate accidentally, because dumps and cuts
naturally come in different sizes. ``tonnage_weighted_variance`` is therefore the only variance
function in this module.

THE IDEAL BOUND, AND WHY IT IS DERIVED RATHER THAN CITED.

If the ``N`` layers a reclaim cut crosses were independent draws from the input distribution, the cut
mean would have variance ``var_in / N``, so

    VRR_ideal = 1 / N            E_ideal = sigma_in / sigma_out = sqrt(N)

Real beds do not reach this. Schramm (AT MINERALS PROCESSING 06/2021) reports a mixing effect ``E`` of
5 to 7.5 for beds of 200 to 600 layers, where the ideal ``sqrt(N)`` would be 14.1 to 24.5. Real
blending therefore recovers roughly a quarter to a third of the ideal benefit, because successive
layers are autocorrelated, a cut does not sample every layer equally, and segregation biases what each
cut contains.

The De Wet (1994) design equation, which the literature cites for this relationship, could not be
verified: Bulk Solids Handling 14(1) p. 93 is not available online and the equation is a rasterised
image in the one paper that quotes it. It is therefore NOT reproduced or attributed here. What is
implemented is the bound above, derived from first principles and labelled as derived.
"""
from __future__ import annotations

import math

VRR_FORMULA_LABEL = "VRR = var_out / var_in (lower is better)"


def tonnage_weighted_mean(values: list[float], weights: list[float]) -> float:
    w = sum(weights)
    if w <= 0.0:
        return 0.0
    return sum(v * t for v, t in zip(values, weights, strict=True)) / w


def tonnage_weighted_variance(values: list[float], weights: list[float]) -> float:
    """Population variance on a tonnage base, which is the base Kumral's requirement demands.

    A count-weighted variance would let a 40 t load and a 400 t cut contribute equally, and since the
    reclaim cuts are typically an order of magnitude larger than the dumps that fed them, the
    resulting VRR would be wrong by roughly that factor.
    """
    w = sum(weights)
    if w <= 0.0:
        return 0.0
    m = tonnage_weighted_mean(values, weights)
    return sum(t * (v - m) ** 2 for v, t in zip(values, weights, strict=True)) / w


def vrr(var_in: float, var_out: float) -> float:
    """The variance reduction ratio. Returns infinity when the input had no variance to reduce."""
    if var_in <= 0.0:
        return math.inf
    return var_out / var_in


def mixing_effect(var_in: float, var_out: float) -> float:
    """``E = sigma_in / sigma_out``, the form the bulk-handling literature quotes design values in.

    Provided because the only quantified anchor for a REAL bed (E of 5 to 7.5 at 200 to 600 layers) is
    published in this form, and converting the product's own result into the anchor's units is what
    makes the comparison honest rather than approximate.
    """
    if var_out <= 0.0:
        return math.inf
    return math.sqrt(var_in / var_out) if var_in > 0.0 else 0.0


def vrr_ideal(n_layers: float) -> float:
    """The independent-layer bound ``1 / N``. Derived, not attributed to a source."""
    return 1.0 / n_layers if n_layers > 0 else math.inf


def blending_efficiency(achieved_vrr: float, n_layers: float) -> float:
    """``VRR_ideal / VRR_achieved``, in (0, 1]. How much of the ideal benefit was actually realised.

    This is the number that keeps the product honest. Reporting an achieved VRR alone invites the
    reader to compare it against zero; reporting it against the bound shows that a bed which looks
    impressive at ``VRR = 0.05`` is only recovering a fifth of what 100 independent layers would give.
    """
    ideal = vrr_ideal(n_layers)
    if not math.isfinite(achieved_vrr) or achieved_vrr <= 0.0 or not math.isfinite(ideal):
        return 0.0
    return min(1.0, ideal / achieved_vrr)


def experimental_variogram(
    values: list[float],
    positions: list[float],
    n_lags: int = 20,
    max_lag: float | None = None,
) -> tuple[list[float], list[float], list[int]]:
    """Matheron's experimental semivariogram of a one-dimensional stream.

    ``gamma(h) = (1 / 2 N(h)) * sum over pairs separated by h of (z_i - z_j)^2``

    ``positions`` is CUMULATIVE TONNAGE, not clock time. A stockpile's input is a one-dimensional lot
    in Gy's sense, and its heterogeneity is a function of mass along the stream, not of how long the
    trucks took. Using time would make the variogram depend on how busy the shift was.

    Returns ``(lag_centres, gamma, pair_counts)``. Lags with fewer than 30 pairs are still returned,
    with their count, so the caller can grey them out rather than silently trusting a noisy tail.
    """
    n = len(values)
    if n < 4:
        return [], [], []
    span = positions[-1] - positions[0]
    if span <= 0:
        return [], [], []
    hmax = max_lag if max_lag is not None else span / 3.0
    width = hmax / n_lags
    sums = [0.0] * n_lags
    counts = [0] * n_lags
    for i in range(n):
        for j in range(i + 1, n):
            h = positions[j] - positions[i]
            if h >= hmax:
                break
            b = int(h / width)
            if b >= n_lags:
                continue
            d = values[i] - values[j]
            sums[b] += d * d
            counts[b] += 1
    centres = [(b + 0.5) * width for b in range(n_lags)]
    gamma = [(sums[b] / (2.0 * counts[b])) if counts[b] > 0 else 0.0 for b in range(n_lags)]
    return centres, gamma, counts


def fit_spherical(centres: list[float], gamma: list[float], counts: list[int]) -> dict[str, float]:
    """Fit a nugget-plus-spherical model by a coarse grid search on the range.

    A grid search rather than a gradient method on purpose: the objective is cheap, the parameter is
    one-dimensional and bounded, and a deterministic search gives byte-identical results across the
    Python and TypeScript implementations, which a gradient method with its own convergence path would
    not. Determinism across lanes is a hard requirement here, not a preference.

    Model: ``gamma(h) = c0 + c * (1.5 h/a - 0.5 (h/a)^3)`` for ``h < a``, and ``c0 + c`` beyond.
    """
    pts = [(h, g, w) for h, g, w in zip(centres, gamma, counts, strict=True) if w >= 5 and h > 0]
    if len(pts) < 4:
        return {"nugget": 0.0, "sill": 0.0, "range": 0.0, "rmse": 0.0}
    hmax = max(h for h, _, _ in pts)
    best = {"nugget": 0.0, "sill": 0.0, "range": 0.0, "rmse": float("inf")}
    for step in range(1, 41):
        a = hmax * step / 40.0
        # linear least squares in (nugget, sill) for this range, weighted by pair count
        sxx = sxy = sx = sy = sw = 0.0
        for h, g, w in pts:
            x = 1.0 if h >= a else (1.5 * (h / a) - 0.5 * (h / a) ** 3)
            sxx += w * x * x
            sxy += w * x * g
            sx += w * x
            sy += w * g
            sw += w
        det = sxx * sw - sx * sx
        if abs(det) < 1e-18:
            continue
        c = (sxy * sw - sx * sy) / det
        c0 = (sxx * sy - sx * sxy) / det
        if c < 0 or c0 < 0:
            c = max(0.0, c)
            c0 = max(0.0, c0)
        err = 0.0
        for h, g, w in pts:
            x = 1.0 if h >= a else (1.5 * (h / a) - 0.5 * (h / a) ** 3)
            err += w * (c0 + c * x - g) ** 2
        rmse = math.sqrt(err / sw)
        if rmse < best["rmse"]:
            best = {"nugget": c0, "sill": c0 + c, "range": a, "rmse": rmse}
    return best
