"""Sector characterization: the working-region rollup, and how far it is from the raw truth.

TWO LEVELS, AND THE CONTENT IS THE DISAGREEMENT BETWEEN THEM.

  RAW is the per-column ledger in ``blocks.py``, at truckload support.
  SECTOR is a named working region, its tonnage-weighted rollup, and its uncertainty.

Sectors come into existence two ways, and both are modelled here.

  BY ROUTING, BEFORE PLACEMENT. Each load is classified from its ore-control estimate and sent to a
  designated area: "Each truckload was classified as high SMR or low SMR based on the grade control
  estimates. The low SMR ore was sent to one stockpile and the high SMR ore was sent to another
  stockpile. One high SMR stockpile and one low SMR stockpile were built at a time" (Neufeld, Lyall
  and Deutsch, CCG Report 8 paper 306, 2006, threshold SMR 1.75).

  BY ANALYSIS, AFTER PLACEMENT. Young and Rogers partition the built pile into quadrants and compare
  the confidence interval of the raw dump observations against that of the interpolated model in each
  one (Minerals 2021, 11, 636, table 3). ``compare`` reproduces that comparison, and the qualitative
  result it must reproduce is that the model's interval is narrower than the data's in every region.

WHY THIS IS THE PRODUCT'S PAYLOAD RATHER THAN A SUMMARY PANEL. The industry baseline is stated plainly
in the same paper: "the resulting stockpile block model currently in place is merely one large,
homogenized block value containing the rolling average grade". One number for the whole pile.
Everything above one number is what the product is for, and the sector view is what an operator would
actually act on: identifying "areas of homogeneity" so that blending "can be intuitively performed by
processing the stockpile in parallel vertical approaches as needed".
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .blocks import BlockModel
from .design import Area
from .terrain import Terrain

# Two-sided normal quantiles, for the confidence levels the published table reports.
_Z = {0.90: 1.6448536269514722, 0.95: 1.959963984540054, 0.99: 2.5758293035489004}
CONFIDENCE_LEVELS = (0.90, 0.95, 0.99)


@dataclass(frozen=True)
class Rollup:
    """What a sector reports about itself.

    ``ci`` maps a confidence level to the half-width of the interval on the MEAN, which is what the
    published table reports. Half-widths rather than bounds, so the numbers are directly comparable
    between the raw observations and the model regardless of where their means sit.
    """

    name: str
    tonnes: float
    mean_grade: float
    stdev: float
    n: int
    ci: dict[float, float]

    def interval(self, level: float = 0.95) -> tuple[float, float]:
        h = self.ci.get(level, 0.0)
        return self.mean_grade - h, self.mean_grade + h


def _summarise(name: str, values: list[float], weights: list[float], tonnes: float) -> Rollup:
    """Weighted mean, weighted standard deviation, and the intervals on the mean."""
    n = len(values)
    if n == 0:
        return Rollup(name, 0.0, 0.0, 0.0, 0, {lv: 0.0 for lv in CONFIDENCE_LEVELS})
    w_tot = sum(weights)
    if w_tot <= 0:
        return Rollup(name, tonnes, 0.0, 0.0, n, {lv: 0.0 for lv in CONFIDENCE_LEVELS})

    mean = sum(v * w for v, w in zip(values, weights, strict=True)) / w_tot
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights, strict=True)) / w_tot
    sd = math.sqrt(max(var, 0.0))
    # Standard error uses the COUNT of observations, not the weight total: the weights express how
    # much material each observation speaks for, not how many independent measurements were made.
    se = sd / math.sqrt(n) if n > 0 else 0.0
    return Rollup(name, tonnes, mean, sd, n, {lv: _Z[lv] * se for lv in CONFIDENCE_LEVELS})


def rollup(
    model: BlockModel, terrain: Terrain, area: Area, *, name: str | None = None
) -> Rollup:
    """Aggregate the raw ledger over one named area, weighting by tonnage.

    Tonnage weighting is not optional. A column holding one load and a column holding forty must not
    count equally toward what the sector says it contains, and an unweighted mean over columns is one
    of the easier ways to produce a confidently wrong grade.
    """
    values: list[float] = []
    weights: list[float] = []
    tonnes = 0.0
    for c in range(model.nx * model.ny):
        if not area.contains(*terrain.xy(c)):
            continue
        g = model.column_grade(c)
        if g is None:
            continue
        t = model.tonnes(c)
        if t <= 0:
            continue
        values.append(g)
        weights.append(t)
        tonnes += t
    return _summarise(name or area.name, values, weights, tonnes)


def rollup_by_lift(
    model: BlockModel, terrain: Terrain, area: Area, lift: int
) -> Rollup:
    """The same aggregation restricted to one lift, which is what exposes internal stratification.

    A sector reporting a single grade can be hiding a pile whose lifts differ substantially, and the
    reclaim sequence decides which of the two the plant actually experiences. Comparing this against
    the whole-area rollup is the honest version of "what is in this sector".
    """
    values: list[float] = []
    weights: list[float] = []
    tonnes = 0.0
    for c in range(model.nx * model.ny):
        if not area.contains(*terrain.xy(c)):
            continue
        num = den = 0.0
        for p in model.columns[c]:
            if p.lift == lift:
                num += p.thickness_m * p.grade
                den += p.thickness_m
        if den <= 0:
            continue
        t = den * model.cell_area_m2 * model.bulk_density_t_m3
        values.append(num / den)
        weights.append(t)
        tonnes += t
    return _summarise(f"{area.name} lift {lift}", values, weights, tonnes)


@dataclass(frozen=True)
class Comparison:
    """A raw-versus-model comparison over one region, in the form of the published table."""

    region: str
    data: Rollup
    model: Rollup

    def model_is_tighter(self, level: float = 0.95) -> bool:
        return self.model.ci[level] < self.data.ci[level]


def compare(
    model: BlockModel,
    terrain: Terrain,
    area: Area,
    observations: list[tuple[float, float, float]],
) -> Comparison:
    """Compare the raw dump observations in a region against the ledger's own rollup for it.

    ``observations`` are ``(x, y, grade)`` per dump event, which is exactly what a fleet-management
    export gives: one row per load, located and assayed. The model side is the interpolated ledger.

    THE BEHAVIOUR THIS MUST REPRODUCE, and the reason it is worth having: in the published study "for
    each quadrant and confidence level, the model has a smaller confidence interval value than that of
    the example data". The model is smoother than the observations because interpolation averages;
    that is a genuine and reportable property, and it is also the reason a sector rollup can look
    reassuring while the raw field underneath it is not.
    """
    vals = [g for x, y, g in observations if area.contains(x, y)]
    data = _summarise(f"{area.name} data", vals, [1.0] * len(vals), 0.0)
    return Comparison(region=area.name, data=data, model=rollup(model, terrain, area))


def quadrants(area: Area) -> list[Area]:
    """Split an area into the four quadrants the published analysis uses.

    Named bottom left, bottom right, top left and top right to match the table, so a reader comparing
    the product against the paper is not translating labels in their head.
    """
    mx, my = area.centre
    return [
        Area(f"{area.name} bottom left", area.x0_m, area.y0_m, mx, my),
        Area(f"{area.name} bottom right", mx, area.y0_m, area.x1_m, my),
        Area(f"{area.name} top left", area.x0_m, my, mx, area.y1_m),
        Area(f"{area.name} top right", mx, my, area.x1_m, area.y1_m),
    ]


def homogeneity_map(
    model: BlockModel, terrain: Terrain, *, window: int = 3
) -> list[float | None]:
    """Local grade dispersion per column, which is where "areas of homogeneity" become visible.

    The paper reads them off a scatter of dump points by eye ("the bottom left part of the figure,
    where many black dots are near each other"). This computes the same thing: the standard deviation
    of column grades in a neighbourhood, low where the material is uniform. ``None`` where there is
    not enough material to say anything, rather than a zero that would read as perfect uniformity.
    """
    out: list[float | None] = []
    for c in range(model.nx * model.ny):
        i, j = c % model.nx, c // model.nx
        vals: list[float] = []
        for dj in range(-window, window + 1):
            for di in range(-window, window + 1):
                ni, nj = i + di, j + dj
                if 0 <= ni < model.nx and 0 <= nj < model.ny:
                    g = model.column_grade(nj * model.nx + ni)
                    if g is not None:
                        vals.append(g)
        if len(vals) < 3:
            out.append(None)
            continue
        m = sum(vals) / len(vals)
        out.append(math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)))
    return out
