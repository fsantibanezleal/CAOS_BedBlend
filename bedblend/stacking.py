"""Method 2, the five industrial stacking geometries, as deposition paths over the pad.

Each function answers one question: given the pad, the number of passes the stacker will make, and
which dump this is, WHERE does the material land? Everything else about how a pile blends follows
from that answer, which is why these are five separate named geometries and not one function with a
"spread" parameter.

DEFINITIONS, cross-checked against the sources rather than paraphrased from memory.

* **Chevron.** The stacker travels the full length of the pad along the centre line, back and forth,
  laying gable-section layers on top of one another. Schramm, "Design of blending beds", AT MINERALS
  PROCESSING 06/2021, defines it in exactly those terms. The layer thickness is the volumetric
  stacking rate divided by the travel speed. Many thin layers, and a strong toe bias, because every
  layer avalanches down the same two flanks.
* **Windrow.** The same longitudinal travel, but the deposition axis moves laterally between passes,
  so the pile is built as parallel cords stacked pyramidally. More intricate to operate, and it
  spreads the toe bias across several crests instead of concentrating it on two flanks.
* **Cone shell.** Successive cones deposited at a stepping position, each shelling over the last.
  Few effective layers per reclaim cut, which is why Bond, Coursaux and Worthington (2000), Loubser
  and de Korte (2015) and Wintz (2011) all report it as unsuitable when homogenization matters.
* **Strata.** Inclined layers built against one flank, the stacker stepping laterally as the pile
  grows. Intermediate blending, and sensitive to the layer inclination.
* **Chevcon.** Chevron travel combined with the stepping of cone shell, producing inclined layers
  along the pile. The best-blending method of the five: Loubser and de Korte measure VRR 0.121 for
  chevcon against 0.232 for cone shell on the same pile, and Bond et al. give a rule of thumb of about
  a ten to one variance reduction for chevcon reclaimed full-face.

WHAT THE PRODUCT MUST REPRODUCE. Not those exact digits, which come from a differently dimensioned
circular pile and whose source is internally inconsistent (see ``plans/stocktwin/findings.md``), but
the ORDER: chevcon below chevron below cone shell.
"""
from __future__ import annotations

import math

METHODS: tuple[str, ...] = ("chevron", "windrow", "coneshell", "strata", "chevcon")

METHOD_LABELS: dict[str, str] = {
    "chevron": "Chevron",
    "windrow": "Windrow",
    "coneshell": "Cone shell",
    "strata": "Strata",
    "chevcon": "Chevcon",
}


def _span(nx: int, cell_m: float, margin_cells: int = 4) -> tuple[float, float]:
    """Usable pad extent along the travel axis, leaving a margin so the toe stays on the pad."""
    lo = margin_cells * cell_m
    hi = (nx - 1 - margin_cells) * cell_m
    return lo, max(lo + cell_m, hi)


def dump_position(
    method: str,
    k: int,
    n_dumps: int,
    *,
    nx: int,
    ny: int,
    cell_m: float,
    n_passes: int,
) -> tuple[float, float]:
    """Pad coordinates for dump ``k`` of ``n_dumps`` under ``method``.

    ``n_passes`` is the number of stacker passes along the pad, which for the longitudinal methods is
    the number of LAYERS the pile ends up with. It is the single most consequential operating
    parameter in the product: it is the ``N`` of the independent-layer bound, and every source in the
    survey agrees that more layers blend better.
    """
    x_lo, x_hi = _span(nx, cell_m)
    y_mid = (ny - 1) * cell_m / 2.0
    u = k / max(1, n_dumps - 1)          # 0 to 1 over the whole build
    passes = max(1, n_passes)

    if method == "chevron":
        # back and forth along the centre line; the triangular wave is the travel
        s = (u * passes) % 2.0
        frac = s if s <= 1.0 else 2.0 - s
        return x_lo + frac * (x_hi - x_lo), y_mid

    if method == "windrow":
        # same longitudinal travel, but the boom slews across a fixed set of cords
        n_cords = 3
        cord = int(u * passes) % n_cords
        s = (u * passes) % 2.0
        frac = s if s <= 1.0 else 2.0 - s
        offset = (cord - (n_cords - 1) / 2.0) * (ny * cell_m) / (n_cords + 1)
        return x_lo + frac * (x_hi - x_lo), y_mid + offset

    if method == "coneshell":
        # a small number of stepping cone positions; each receives many consecutive dumps
        n_cones = max(2, passes // 6)
        cone = min(n_cones - 1, int(u * n_cones))
        return x_lo + (cone + 0.5) / n_cones * (x_hi - x_lo), y_mid

    if method == "strata":
        # inclined layers built against one flank: the deposition axis marches across the pad while
        # travelling longitudinally, so each layer leans
        s = (u * passes) % 2.0
        frac = s if s <= 1.0 else 2.0 - s
        lean = (u - 0.5) * (ny * cell_m) * 0.55
        return x_lo + frac * (x_hi - x_lo), y_mid + lean

    if method == "chevcon":
        # chevron travel plus a slow longitudinal advance of the whole pattern, so layers are
        # inclined cones along the pile rather than parallel gables
        s = (u * passes) % 2.0
        frac = s if s <= 1.0 else 2.0 - s
        window = 0.55 * (x_hi - x_lo)
        origin = x_lo + u * (x_hi - x_lo - window)
        return origin + frac * window, y_mid

    raise ValueError(f"unknown stacking method {method!r}; expected one of {METHODS}")


def layers_per_cut(method: str, n_passes: int) -> int:
    """How many stacked layers a full-face cut should cross, from the geometry alone.

    A prediction, not a measurement, and it is reported next to the MEASURED layer count the ledger
    produces. When the two disagree the geometry is doing something the operator did not intend,
    which is exactly the kind of thing a teaching tool should surface rather than hide.
    """
    passes = max(1, n_passes)
    if method in ("chevron", "windrow"):
        return passes
    if method == "chevcon":
        return max(1, int(passes * 0.55))
    if method == "strata":
        return max(1, int(passes * 0.7))
    if method == "coneshell":
        return max(1, math.ceil(passes / max(2, passes // 6)))
    raise ValueError(f"unknown stacking method {method!r}")
