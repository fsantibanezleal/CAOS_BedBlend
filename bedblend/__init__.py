"""bedblend, a bed-blending stockpile engine.

A blending bed is the cheapest variance reduction available in a mineral processing plant: material
is stacked in many thin layers and reclaimed across all of them at once, so the cut delivered to the
mill is an average over the layers it crosses rather than over whichever truck arrived last. This
library computes what that averaging actually achieves for a given pile, including the common case
where it achieves very little.

Five things happen in a pile, and each is its own module:

* `heightfield`, the pile stands at a repose angle, so a deposit avalanches until no local slope
  exceeds it. A mass-conserving priority cascade with a water-filling toppling rule on a pad grid.
* `segregation`, as the material avalanches the flowing layer sorts by size: fines percolate down
  through the gaps and coarse particles ride to the surface and run further. Gray and Thornton's
  kinetic sieving, solved with a Godunov flux so the concentration shocks survive rather than being
  smeared.
* `pile`, every cell carries a stack of lots, so every reclaimed tonne traces back to the truck loads
  that made it, and the four reclaim geometries differ in how many stacked layers a cut crosses.
* `stacking`, the five geometries a stacker can build: chevron, windrow, cone shell, chevcon, strata.
* `blending`, the verdict: variance reduction on a tonnage base, experimental variograms, residence
  time, and the honest comparison against the ideal 1/N bound.

The core is dependency-free by design, plain Python floats and lists rather than numpy, because it is
small, it has to be reproducible bit for bit against a browser implementation of the same equations,
and a core with no dependencies installs anywhere in seconds.

Nothing here is product-specific. Case registries, ingestion contracts, artifact manifests and web
export belong to the application that consumes this engine, not to the engine.
"""
from __future__ import annotations

__version__ = "0.01.000"

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
from .heightfield import cascade, critical_drop, max_slope_excess, neighbour_table
from .pile import RECLAIM_GEOMETRY, Pile
from .rtd import character, dimensionless_variance, histogram, mean_and_sd
from .run import (
    RECLAIM_LABELS,
    RECLAIM_METHODS,
    RunConfig,
    input_variogram,
    measure,
    output_variogram,
    simulate,
)
from .schema import BlendMetrics, Lot, PadSpec, ReclaimCut, RunResult, TruckDump
from .segregation import NZ_DEFAULT, FlowingLayer, segregation_number
from .stacking import METHOD_LABELS, METHODS, dump_position, layers_per_cut
from .stream import STRUCTURES, cumulative_tonnes, generate_stream

__all__ = [
    "METHODS",
    "METHOD_LABELS",
    "NZ_DEFAULT",
    "RECLAIM_GEOMETRY",
    "RECLAIM_LABELS",
    "RECLAIM_METHODS",
    "STRUCTURES",
    "VRR_FORMULA_LABEL",
    "BlendMetrics",
    "FlowingLayer",
    "Lot",
    "PadSpec",
    "Pile",
    "ReclaimCut",
    "RunConfig",
    "RunResult",
    "TruckDump",
    "__version__",
    "blending_efficiency",
    "cascade",
    "character",
    "critical_drop",
    "cumulative_tonnes",
    "dimensionless_variance",
    "dump_position",
    "experimental_variogram",
    "fit_spherical",
    "generate_stream",
    "histogram",
    "input_variogram",
    "layers_per_cut",
    "max_slope_excess",
    "mean_and_sd",
    "measure",
    "mixing_effect",
    "neighbour_table",
    "output_variogram",
    "segregation_number",
    "simulate",
    "tonnage_weighted_mean",
    "tonnage_weighted_variance",
    "vrr",
    "vrr_ideal",
]
