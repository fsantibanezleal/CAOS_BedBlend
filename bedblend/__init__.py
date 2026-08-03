"""bedblend, an engine for truck-built ROM stockpiles.

WHAT THIS MODELS. A heaped-fill, truck-dumped, pre-crusher run-of-mine stockpile: the kind built on a
prepared pad by haul trucks and a dozer, lift by lift, and reclaimed by a loader working a face. It is
the inverse of an open pit. A pit cuts benches downward; a stockpile adds lifts upward, with the same
primitives, a working level, a face at the angle of repose, a berm, and a ramp giving access to the
next level. Reclaim inverts it again.

WHAT IT DOES NOT MODEL, said plainly because the two systems are constantly conflated. Chevron,
windrow and cone-shell beds are built by CONVEYOR STACKERS, not by trucks. Of the five pre-crusher
stockpile types, only blended-in-blended-out is a chevron, and the stockpile software that exists "is
tailored to conveyor systems for intermediate stockpiles" (Young and Rogers, Minerals 2021, 11, 636,
figure 1). Trucks do not build a chevron bed. Offering those geometries alongside trucks is a category
error, and an earlier version of this library made it.

THE MODULES, in the order material moves through them:

* ``terrain``     the ground, plus the two fields derived from it that constrain every machine: the
                  crest of the working level, and trafficability
* ``design``      the dump plan: named areas, a bench schedule, a reserved access ramp, and the tip
                  positions that follow. A dump record locates a load by the "name and bench height of
                  dump location polygon", so areas and levels are the operational data model
* ``stream``      the incoming loads, generated from a DIG SEQUENCE. Grade autocorrelation is an
                  output of the shovel's dwell, not an input parameter
* ``truck``       machines with routes over drivable ground, spotting, and retained approach and
                  departure paths
* ``dump``        the two placement regimes. A paddock heap is an elliptical frustum sized by the
                  truck; an edge dump cascades down the face perpendicular to the crest tangent, in
                  one of four profiles measured across 28 UAV-surveyed dumps
* ``relax``       mass-conserving relaxation that HOLDS the angle of repose, in two stages, because a
                  fresh heap stands at about 2:1 and slumps to repose afterwards
* ``dozer``       levels the floor, pushes material over the face, raises berms, and reports how far
                  it displaced everything
* ``blocks``      the raw ledger at truckload support, carrying grade uncertainty and displacement
* ``sectors``     working-region rollups and the raw-versus-model comparison
* ``reclaim``     sequenced extraction from a face, in LIFO, FIFO or full-height order
* ``build``       the loop that makes the above a system
* ``segregation`` Gray and Thornton's kinetic sieving, solved with a Godunov flux
* ``blending``    the verdict: variance reduction on a tonnage base, variograms, the 1/N bound
* ``rtd``         residence time

THE THREE THINGS THIS ENGINE REFUSES TO PRETEND. Material placed at the angle of repose cannot be
driven on, so a pile constrains its own construction and an unreachable tip is reported rather than
served. A dozer mixes material "in intractable ways", so provenance is reported with a displacement
attached rather than to twelve decimal places. And ore-control grade is already uncertain by 5 to 20
percent before a truck moves, so a load's grade carries that with it.

The core is dependency-free by design, plain Python floats and lists rather than numpy, because it has
to be reproducible bit for bit against a browser implementation of the same equations and a core with
no dependencies installs anywhere in seconds.

Nothing here is product-specific. Case registries, ingestion contracts, artifact manifests and web
export belong to the application that consumes this engine, not to the engine.
"""
from __future__ import annotations

__version__ = "0.04.001"

from .blending import (
    VRR_FORMULA_LABEL,
    blending_efficiency,
    experimental_variogram,
    fit_spherical,
    mixing_effect,
    tonnage_weighted_mean,
    tonnage_weighted_variance,
    vrr,
    vrr_ideal,
)
from .blocks import BlockModel, Parcel, transfer_distances
from .build import BuildResult, LoadRecord, build
from .design import Area, Bench, DumpPlan, Phase, TipPosition, rectangular_yard
from .dozer import DozerPass, build_berm, level, push_to_crest
from .dump import (
    MEASURED_ANGLE_DEG,
    MEASURED_LENGTH_M,
    MEASURED_THICKNESS_M,
    MEASURED_VOLUME_M3,
    MEASURED_WIDTH_M,
    PROFILE_STATS,
    DumpProfile,
    Placement,
    ProfileStats,
    classify,
    distance_to_crest,
    place_edge,
    place_paddock,
    run_out_for_bench,
)
from .facesegregation import (
    FaceSegregation,
    apparent_repose_deg,
    intensity,
    segregate_face,
    segregation_index,
)
from .material import (
    COMPACTION_BAND,
    DEFAULT_MATERIAL,
    SWELL_HARD_ROCK,
    Material,
    SizeSplit,
)
from .reclaim import Cut, ReclaimFace, ReclaimMethod, advance, campaign, cut
from .relax import (
    FRESH_HEAP_DEG,
    FRESH_HEAP_SLOPE,
    ReposeViolation,
    assert_stable,
    cascade,
    count_over_repose,
    critical_drop,
    max_slope_excess,
    neighbour_table,
    relax_to,
    settle,
)
from .rtd import character, dimensionless_variance, histogram, mean_and_sd
from .sectors import (
    CONFIDENCE_LEVELS,
    Comparison,
    Rollup,
    compare,
    homogeneity_map,
    quadrants,
    rollup,
    rollup_by_lift,
)
from .segregation import CFL, NZ_DEFAULT, FlowingLayer, segregation_number
from .stream import (
    DigBlock,
    DigSequence,
    Xorshift,
    cumulative_tonnes,
    dig_sequence,
    measured_range_t,
    payloads_from,
)
from .terrain import EMPTY_M, Terrain, TruckSpec
from .topography import FillType, buildable_fraction, ground, relief_stats
from .truck import (
    CycleState,
    Fleet,
    NoRoute,
    Payload,
    Route,
    Truck,
    passable_mask,
    reachable_mask,
    solve_route,
    spot,
)

# ``compare`` is a very generic name at the package root, so the sector comparison also has an
# explicit alias. Both point at the same function.
sectors_compare = compare

__all__ = [
    "CFL",
    "COMPACTION_BAND",
    "CONFIDENCE_LEVELS",
    "DEFAULT_MATERIAL",
    "EMPTY_M",
    "FRESH_HEAP_DEG",
    "FRESH_HEAP_SLOPE",
    "MEASURED_ANGLE_DEG",
    "MEASURED_LENGTH_M",
    "MEASURED_THICKNESS_M",
    "MEASURED_VOLUME_M3",
    "MEASURED_WIDTH_M",
    "NZ_DEFAULT",
    "PROFILE_STATS",
    "SWELL_HARD_ROCK",
    "VRR_FORMULA_LABEL",
    "Area",
    "Bench",
    "BlockModel",
    "BuildResult",
    "Comparison",
    "Cut",
    "CycleState",
    "DigBlock",
    "DigSequence",
    "DozerPass",
    "DumpPlan",
    "DumpProfile",
    "FaceSegregation",
    "FillType",
    "Fleet",
    "FlowingLayer",
    "LoadRecord",
    "Material",
    "NoRoute",
    "Parcel",
    "Payload",
    "Phase",
    "Placement",
    "ProfileStats",
    "ReclaimFace",
    "ReclaimMethod",
    "ReposeViolation",
    "Rollup",
    "Route",
    "SizeSplit",
    "Terrain",
    "TipPosition",
    "Truck",
    "TruckSpec",
    "Xorshift",
    "advance",
    "apparent_repose_deg",
    "assert_stable",
    "blending_efficiency",
    "build",
    "build_berm",
    "buildable_fraction",
    "campaign",
    "cascade",
    "character",
    "classify",
    "compare",
    "count_over_repose",
    "critical_drop",
    "cumulative_tonnes",
    "cut",
    "dig_sequence",
    "dimensionless_variance",
    "distance_to_crest",
    "experimental_variogram",
    "fit_spherical",
    "ground",
    "histogram",
    "homogeneity_map",
    "intensity",
    "level",
    "max_slope_excess",
    "mean_and_sd",
    "measured_range_t",
    "mixing_effect",
    "neighbour_table",
    "passable_mask",
    "payloads_from",
    "place_edge",
    "place_paddock",
    "push_to_crest",
    "quadrants",
    "reachable_mask",
    "rectangular_yard",
    "relax_to",
    "relief_stats",
    "rollup",
    "rollup_by_lift",
    "run_out_for_bench",
    "sectors_compare",
    "segregate_face",
    "segregation_index",
    "segregation_number",
    "settle",
    "solve_route",
    "spot",
    "tonnage_weighted_mean",
    "tonnage_weighted_variance",
    "transfer_distances",
    "vrr",
    "vrr_ideal",
]
