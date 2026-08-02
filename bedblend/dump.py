"""How a truck load actually lands, in the two regimes and the four measured shapes.

THIS MODULE REPLACES A SYMMETRIC 4.5 m DISC. The previous engine placed every load as an isotropic
cosine bell of fixed radius, with no heading and no face. Twenty-eight real dumps measured by UAV
photogrammetry say that is wrong in every dimension at once: they are 13 to 46 m long, 11 to 23 m wide
and 0.37 to 2.03 m thick, they are strongly directional, and they come in four distinct shapes
(Young and Rogers, Mining 2022, 2(1), 86-102, doi:10.3390/mining2010006, table 5). A 4.5 m isotropic
disc is an order of magnitude short in the down-face axis and has no direction at all.

THE TWO REGIMES. From the companion paper: material "forms a small heap if it is dumped on a flat
surface, or cascades along the edge of a dump face if dumped over a developing dump, stockpile or
dump/heap leach" (Mining 2022). Those are the two operators here, and they are not variants of one
another.

  PADDOCK, on flat ground. "the resulting heap of material takes on geometric form similar to that of
  an elliptical frustum. The height, length and width of the heap are dependent on the respective
  height, width and length of the haul truck used" (Minerals 2021, 11, 636, figure 11). Emplaced at
  roughly 2:1 and settling to repose afterwards, which ``relax.settle`` handles.

  EDGE, over a crest. "the volume of influence for the haul truck in the upper layer/edge dump case is
  that of dimensions in width equal to the width of the haul truck, length equal to the horizontal
  component of the bench slope and variable height ... This volume runs perpendicular to the tangent
  of the dump location" (Minerals 2021, figure 13). Perpendicular to the crest tangent is the outward
  normal of the face, so the load is oriented by the terrain, not by the truck's compass heading. The
  cascade "typically aggregates more at the bottom of the dumping area under normal conditions and
  less near the top crest".

WHICH SHAPE FORMS IS DECIDED BY DISTANCE TO THE CREST, and that is a measured result rather than an
assumption: "if the truck dumps far from the crest of the dump face, it will create a sloughed heap.
When the truck dumps against the crest of the dump face, the type of the resulting dump profile is
either comet, oval or rectangular" (Mining 2022, section 4.2). This is the direct answer to the
question of how a truck's position and direction define the area it feeds.

WHAT IS HONESTLY NOT DETERMINED. The paper is explicit that it could not say which of comet, oval or
rectangular forms from position alone, and that its hypothesis about uneven tray loading was never
tested: "the exact interplay between how the trucks were loaded and the resulting dump profiles
remains unclear, and no information on truck loading was gathered during this study". So the choice
among the three is drawn from their measured frequencies, seeded, rather than being predicted from a
mechanism this model does not have. The frequencies are real; the selection is admittedly stochastic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .terrain import Terrain, TruckSpec


class DumpProfile(str, Enum):
    """The four shapes measured across 28 UAV-surveyed dumps (Mining 2022, table 5), plus the heap.

    ``PADDOCK`` is not one of the four. Those four are cascade profiles, all of them shapes taken by
    material that went over a face. A load tipped on flat ground is a different object with a different
    published description, the elliptical frustum of Minerals 2021 figure 11, and collapsing it into
    the cascade taxonomy would misreport what was placed.
    """

    OVAL = "oval"
    COMET = "comet"
    RECTANGULAR = "rectangular"
    SLOUGHED_HEAP = "sloughed_heap"
    PADDOCK = "paddock"


@dataclass(frozen=True)
class ProfileStats:
    """Per-type measurements read from Mining 2022, figures 2 to 7 and table 5.

    Carried in the code rather than in a comment because the calibration test asserts the operator's
    output against these numbers. If the operator drifts out of the measured band, the test fails and
    the operator is wrong, which is the kill criterion the plan states.
    """

    mean_volume_m3: float
    mean_angle_deg: float
    mean_width_m: float
    mean_thickness_m: float
    count: int


# Counts are the 28 classified dumps in table 5. Means are read from the per-type box charts.
PROFILE_STATS: dict[DumpProfile, ProfileStats] = {
    DumpProfile.OVAL: ProfileStats(128.0, 34.5, 14.8, 1.00, 12),
    DumpProfile.COMET: ProfileStats(134.0, 33.5, 19.4, 1.50, 6),
    DumpProfile.RECTANGULAR: ProfileStats(137.0, 34.0, 13.0, 0.95, 4),
    DumpProfile.SLOUGHED_HEAP: ProfileStats(129.0, 24.5, 14.6, 1.40, 6),
}

# Whole-population ranges from table 5, used as the calibration envelope.
MEASURED_LENGTH_M = (13.0, 46.0)
MEASURED_WIDTH_M = (11.0, 23.0)
MEASURED_THICKNESS_M = (0.368, 2.032)
MEASURED_ANGLE_DEG = (12.0, 36.0)
MEASURED_VOLUME_M3 = (94.0, 155.0)

# Beyond roughly one truck length back from the crest the load can no longer reach the face, so it
# bunches and only partly sloughs over. The operational rule of thumb is to tip about one truck length
# back from an edge, which is where this threshold comes from; it is a rule of thumb, not a measured
# constant, and it is a parameter of the classifier rather than a hidden literal.
SLOUGH_DISTANCE_TRUCK_LENGTHS = 1.0

# How far down the face a sloughed heap reaches, as a fraction of the full run-out. The six sloughed
# heaps in table 5 measure 13, 16, 27, 28, 29 and 39 m long, a mean of about 25 m, against run-outs of
# roughly 30 m at these bench heights.
SLOUGH_EXTENT = 0.85


def classify(
    distance_to_crest_m: float,
    truck: TruckSpec,
    *,
    rand: float = 0.5,
    slough_truck_lengths: float = SLOUGH_DISTANCE_TRUCK_LENGTHS,
) -> DumpProfile:
    """Pick the dump profile from the truck's distance to the crest.

    Far from the crest gives a sloughed heap; against the crest gives one of the other three, drawn
    from their measured relative frequencies using ``rand`` in [0, 1). The caller supplies ``rand``
    from a seeded stream so a run stays reproducible.
    """
    if distance_to_crest_m > slough_truck_lengths * truck.body_length_m:
        return DumpProfile.SLOUGHED_HEAP

    at_crest = (DumpProfile.OVAL, DumpProfile.COMET, DumpProfile.RECTANGULAR)
    total = sum(PROFILE_STATS[p].count for p in at_crest)
    acc = 0.0
    for p in at_crest:
        acc += PROFILE_STATS[p].count / total
        if rand < acc:
            return p
    return DumpProfile.OVAL


def _width_shape(profile: DumpProfile, s: float) -> float:
    """Relative width of the deposit at down-face position ``s``, with 0 at the crest and 1 at the toe.

    Each curve is the paper's verbal description of that shape turned into the simplest function that
    reproduces it, and nothing more is claimed for the functional forms than that.
    """
    if profile is DumpProfile.OVAL:
        # "narrow at crest and toe, maximum width midway down the dump face"
        return math.sin(math.pi * s) ** 0.6
    if profile is DumpProfile.COMET:
        # "large volume near the base, narrow trail extending up the face"
        return s ** 0.8
    if profile is DumpProfile.RECTANGULAR:
        # "covers the whole dump face evenly to uniform width"
        return 1.0
    # Sloughed heap: bunched near the crest, and it "does not typically extend the full length of the
    # dump face", which is the paper's own explanation for why this type's mean angle is 24.5 degrees
    # against 33 to 35 for the others. The extent is set so the realised length lands on the measured
    # mean for this type, about 25 m against a 30 m run-out.
    return math.sin(math.pi * min(s / SLOUGH_EXTENT, 1.0)) ** 0.5 if s <= SLOUGH_EXTENT else 0.0


def _mass_shape(profile: DumpProfile, s: float) -> float:
    """Relative areal mass at down-face position ``s``.

    For the three cascading types the measured statement is that material "aggregates more at the
    bottom of the dumping area under normal conditions and less near the top crest", so density grows
    toward the toe. The sloughed heap is the opposite by definition: it never got there.
    """
    if profile is DumpProfile.SLOUGHED_HEAP:
        # Bunched at the crest and thinning away from it, over the same extent the width uses.
        return max(0.0, 1.0 - s / SLOUGH_EXTENT)
    return 0.35 + 0.65 * s


@dataclass(frozen=True)
class Placement:
    """What one dump actually did, for the ledger and for the visualisation.

    ``cells`` and ``added_m`` are parallel. ``length_m``, ``width_m`` and ``max_thickness_m`` are the
    realised geometry, measured back off the placed field rather than copied from the request, because
    those are the quantities the calibration test compares against the published table.
    """

    profile: DumpProfile
    cells: list[int]
    added_m: list[float]
    volume_m3: float
    length_m: float
    width_m: float
    max_thickness_m: float
    heading_rad: float
    distance_to_crest_m: float


def _apply(terrain: Terrain, weights: dict[int, float], volume_m3: float) -> tuple[list[int], list[float]]:
    """Scale a weight map to the requested volume and add it to the surface.

    Mass conservation is exact by construction: the weights are normalised so the added volume equals
    the requested volume, and no clipping happens afterwards. Any load whose footprint falls partly
    off the pad is concentrated on the part that remains rather than losing tonnes over the edge, which
    matches the pad-as-a-wall convention the relaxation solver uses.
    """
    total = sum(weights.values())
    if total <= 0.0:
        return [], []
    scale = volume_m3 / (total * terrain.cell_m * terrain.cell_m)
    cells: list[int] = []
    added: list[float] = []
    for c, w in weights.items():
        dz = w * scale
        if dz <= 0.0:
            continue
        terrain.z[c] += dz
        cells.append(c)
        added.append(dz)
    return cells, added


def _measure(terrain: Terrain, cells: list[int], added: list[float], u: tuple[float, float]) -> tuple[float, float, float]:
    """Realised ``(length, width, max thickness)`` of a placement, length along ``u``.

    Measured off the footprint so the calibration test is checking what was built, not what was asked
    for. Extents are taken between cell centres and widened by one cell, since a single-cell deposit
    still occupies a cell rather than a point.
    """
    if not cells:
        return 0.0, 0.0, 0.0
    ux, uy = u
    if abs(ux) < 1e-12 and abs(uy) < 1e-12:
        ux, uy = 1.0, 0.0
    px, py = -uy, ux
    along: list[float] = []
    across: list[float] = []
    for c in cells:
        x, y = terrain.xy(c)
        along.append(x * ux + y * uy)
        across.append(x * px + y * py)
    return (
        max(along) - min(along) + terrain.cell_m,
        max(across) - min(across) + terrain.cell_m,
        max(added),
    )


def place_paddock(
    terrain: Terrain,
    x_m: float,
    y_m: float,
    heading_rad: float,
    volume_m3: float,
    truck: TruckSpec,
    *,
    spread: float = 1.0,
) -> Placement:
    """Place a load as an elliptical frustum on flat ground, sized by the truck.

    The footprint's long axis lies along ``heading_rad``. Its semi-axes come from the machine: the
    truck's body length along the heading and its bed width across, both scaled by ``spread``, which
    is how the source's two caveats are expressed. Truck movement during discharge extends the heap
    "not the width", and the width "may also expand beyond the original width of the truck if the truck
    does not move forward".

    The frustum has a flat top over the inner 40 percent of the footprint, declining linearly to zero
    at its edge. Height is not a parameter: it follows from conserving the load's volume, which is why
    the shape can be stated from the truck alone.
    """
    a = 0.5 * truck.body_length_m * spread     # semi-axis along the heading
    b = 0.5 * truck.bed_width_m * spread       # semi-axis across it
    ux, uy = math.cos(heading_rad), math.sin(heading_rad)
    px, py = -uy, ux

    reach = max(a, b) + terrain.cell_m
    weights: dict[int, float] = {}
    for c in _cells_within(terrain, x_m, y_m, reach):
        cx, cy = terrain.xy(c)
        dx, dy = cx - x_m, cy - y_m
        # Normalised elliptical radius in the heading frame.
        r = math.hypot((dx * ux + dy * uy) / a, (dx * px + dy * py) / b)
        if r > 1.0:
            continue
        weights[c] = 1.0 if r <= 0.4 else (1.0 - r) / 0.6

    cells, added = _apply(terrain, weights, volume_m3)
    length, width, thick = _measure(terrain, cells, added, (ux, uy))
    return Placement(
        profile=DumpProfile.PADDOCK,
        cells=cells,
        added_m=added,
        volume_m3=volume_m3,
        length_m=length,
        width_m=width,
        max_thickness_m=thick,
        heading_rad=heading_rad,
        distance_to_crest_m=float("inf"),
    )


def place_edge(
    terrain: Terrain,
    x_m: float,
    y_m: float,
    volume_m3: float,
    truck: TruckSpec,
    *,
    profile: DumpProfile,
    run_out_m: float,
    normal: tuple[float, float] | None = None,
    distance_to_crest_m: float = 0.0,
    width_scale: float = 1.0,
) -> Placement:
    """Cascade a load down the face, oriented by the terrain rather than by the truck's heading.

    ``normal`` is the outward normal of the face, which is "perpendicular to the tangent of the dump
    location". If it is not supplied it is taken from the terrain at the dump cell, which is the
    correct source: the plan was written before the face moved, and the face is where the material
    actually goes.

    ``run_out_m`` is the down-face extent, the "length equal to the horizontal component of the bench
    slope". The caller computes it from the bench height and the face angle, because the dump operator
    does not know the bench schedule.

    Base width is the truck's bed width, per the measurement, scaled by ``width_scale``. The comet
    type is measurably the widest and the rectangular the narrowest, and those factors come from the
    per-type means rather than from taste.
    """
    c0 = terrain.cell_at(x_m, y_m)
    if c0 is None:
        return Placement(profile, [], [], 0.0, 0.0, 0.0, 0.0, 0.0, distance_to_crest_m)

    nx_, ny_ = normal if normal is not None else terrain.outward_normal(c0)
    if abs(nx_) < 1e-12 and abs(ny_) < 1e-12:
        # No face here. A load tipped onto flat ground is a heap, not a cascade, and pretending
        # otherwise would manufacture a streak where the terrain has nowhere to send it.
        return place_paddock(terrain, x_m, y_m, 0.0, volume_m3, truck)

    px, py = -ny_, nx_
    # WIDTH IS MEASURED, NOT THE TRUCK'S. The paper's figure-13 assumption is that the volume of
    # influence is "width equal to the width of the haul truck", but the widths actually measured on
    # the 28 surveyed dumps are 11 to 23 m against a 7.3 m bed. The material spreads as it descends,
    # and the paper says why for the widest type: comet profiles are "the result of additional material
    # from the dump face aggregating with the dump mass as it cascades, resulting in an increase in
    # width". So the operator is calibrated to the measured maximum width per type, and the truck's bed
    # width sets only the streak's width AT THE CREST, where nothing has spread yet.
    w_max = PROFILE_STATS[profile].mean_width_m * width_scale
    half_w = 0.5 * w_max
    crest_frac = min(1.0, truck.bed_width_m / w_max) if w_max > 0 else 1.0

    reach = run_out_m + half_w + terrain.cell_m
    weights: dict[int, float] = {}
    for c in _cells_within(terrain, x_m, y_m, reach):
        cx, cy = terrain.xy(c)
        dx, dy = cx - x_m, cy - y_m
        s_m = dx * nx_ + dy * ny_          # distance down the face
        t_m = dx * px + dy * py            # distance across it
        if s_m < 0.0 or s_m > run_out_m:
            continue
        s = s_m / run_out_m if run_out_m > 0 else 0.0
        shape = _width_shape(profile, s)
        if shape <= 0.0:
            continue   # past the extent of this profile; a sloughed heap stops short of the toe
        # The streak is never narrower than the tray that poured it, so the shape functions are
        # floored at the crest width instead of tapering to a physically impossible point.
        half = half_w * max(shape, crest_frac)
        if abs(t_m) > half:
            continue
        # Across-face taper, so the streak has edges rather than a cliff.
        lateral = 1.0 - (abs(t_m) / half) ** 2
        w = _mass_shape(profile, s) * lateral
        if w > 0.0:
            weights[c] = w

    cells, added = _apply(terrain, weights, volume_m3)
    length, width, thick = _measure(terrain, cells, added, (nx_, ny_))
    return Placement(
        profile=profile,
        cells=cells,
        added_m=added,
        volume_m3=volume_m3,
        length_m=length,
        width_m=width,
        max_thickness_m=thick,
        heading_rad=math.atan2(ny_, nx_),
        distance_to_crest_m=distance_to_crest_m,
    )


def run_out_for_bench(bench_height_m: float, face_angle_deg: float) -> float:
    """The "horizontal component of the bench slope": how far a cascade reaches down the face.

    This is the quantity that makes an edge dump 13 to 46 m long while a paddock heap is a truck long.
    A 20 m bench at 34 degrees runs out about 30 m, which sits in the middle of the measured band, and
    that agreement is a check on the whole geometry rather than a coincidence.
    """
    ang = max(min(face_angle_deg, 89.0), 1.0)
    return bench_height_m / math.tan(math.radians(ang))


def _cells_within(terrain: Terrain, x_m: float, y_m: float, reach_m: float) -> list[int]:
    """Cell indices whose centres lie within ``reach_m`` of a point, clipped to the pad.

    A bounding-box scan rather than a whole-pad sweep. On a 300 by 300 pad the difference between
    scanning a 40 m neighbourhood and scanning 90,000 cells per load is the difference between a
    responsive model and an unusable one.
    """
    i0 = max(int((x_m - reach_m) // terrain.cell_m), 0)
    i1 = min(int((x_m + reach_m) // terrain.cell_m), terrain.nx - 1)
    j0 = max(int((y_m - reach_m) // terrain.cell_m), 0)
    j1 = min(int((y_m + reach_m) // terrain.cell_m), terrain.ny - 1)
    out: list[int] = []
    for j in range(j0, j1 + 1):
        base = j * terrain.nx
        for i in range(i0, i1 + 1):
            out.append(base + i)
    return out


def distance_to_crest(terrain: Terrain, x_m: float, y_m: float, crest: list[int]) -> float:
    """Straight-line distance from a tip position to the nearest crest cell, in metres.

    Returns infinity when there is no crest, which is the correct answer on an empty pad: there is no
    face to dump over, so every load is a paddock heap. That is exactly the state a stockpile starts
    in, and it is why the base layer is built the way it is.
    """
    if not crest:
        return float("inf")
    best = float("inf")
    for c in crest:
        cx, cy = terrain.xy(c)
        d = math.hypot(cx - x_m, cy - y_m)
        best = min(best, d)
    return best
