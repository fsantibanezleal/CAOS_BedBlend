"""Typed objects passed between pipeline stages, the inter-stage contract.

Plain frozen dataclasses so the whole core stays importable anywhere, including a stripped-down
interpreter. Units are stated on every field because a stockpile mixes tonnes, metres, percent and
grams per tonne, and a silent unit error is the easiest way to produce a plausible wrong answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PadSpec:
    """The stockpile pad: a rectangular grid of square cells with an imposed angle of repose.

    ``repose_deg`` is a MATERIAL property that is imposed on the relaxation solver, not an emergent
    property of it. Published handbook values for ores span roughly 34 to 60 degrees; the default
    below sits in the middle of the crushed-copper-ore part of that range. See
    ``docs/methods/01_relaxation.md`` for the honest statement of what the solver does and does not
    claim.
    """

    nx: int = 64                 # cells along the pad axis (the direction a stacker travels)
    ny: int = 24                 # cells across the pad
    cell_m: float = 3.0          # m, square cell edge
    repose_deg: float = 37.0     # degrees, imposed critical slope of the fines-dominant material
    repose_coarse_deg: float = 37.0  # degrees, repose angle of the coarse species; a POSITIVE
    #                                  difference against ``repose_deg`` is the Makse stratification
    #                                  condition (coarse steeper than fines)
    bulk_density_tpm3: float = 1.9   # t/m3, loose bulk density of crushed ore

    @property
    def cell_area_m2(self) -> float:
        return self.cell_m * self.cell_m

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny


@dataclass(frozen=True)
class TruckDump:
    """One validated dump event: a truck emptying a load onto the pad.

    This is the row shape a real fleet-management export produces, and it is what CONTRACT 1
    validates. ``coarse_frac`` is the volume fraction of the coarse size class in the load, which is
    what the segregation solver transports; a monodisperse load has ``coarse_frac`` of 0 or 1 and
    cannot segregate at all.
    """

    event_id: int
    t_s: float                   # s, event time on the pad clock
    truck_id: str
    source_id: str               # dig block or polygon the load came from
    tonnes: float                # t
    grade_cu_pct: float          # percent Cu
    grade_au_gpt: float = 0.0    # g/t Au
    coarse_frac: float = 0.35    # volume fraction in the coarse size class, 0 to 1
    moisture_pct: float = 3.0    # percent
    x_m: float = 0.0             # m, dump easting on the pad
    y_m: float = 0.0             # m, dump northing on the pad


@dataclass(frozen=True)
class Lot:
    """One parcel of material sitting somewhere in the pile.

    A lot is the unit of traceability. It carries the id of the deposition event it came from, so a
    reclaim cut can report which dumps fed it and in what proportion. ``coarse_frac`` is tracked per
    lot because segregation changes it as the material avalanches: the lot deposited at the toe is
    not the lot that left the truck.
    """

    event_id: int
    tonnes: float
    grade_cu_pct: float
    grade_au_gpt: float
    coarse_frac: float
    t_s: float


@dataclass(frozen=True)
class ReclaimCut:
    """One reclaim action and its complete provenance.

    ``sources`` maps deposition event id to the FRACTION of this cut's tonnage that came from it. The
    fractions sum to one, and that identity is a test invariant rather than a comment: a ledger that
    loses or double-counts material will violate it immediately.
    """

    cut_id: int
    t_s: float
    tonnes: float
    grade_cu_pct: float
    grade_au_gpt: float
    coarse_frac: float
    n_layers: int                          # distinct deposition events this cut crossed
    residence_s: float                     # tonnage-weighted mean time the material spent in the pile
    sources: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BlendMetrics:
    """The value the product exists to measure, for one run.

    ``vrr`` is ``var_out / var_in``. LOWER IS BETTER. This direction follows Kumral (2006) as used by
    Loubser and de Korte (2015), whose own results confirm it (coneshell 0.232 is worse than chevcon
    0.121). The reciprocal convention also circulates, which is exactly why the formula is displayed
    next to the number everywhere in the product.
    """

    var_in: float
    var_out: float
    vrr: float
    mean_in: float
    mean_out: float
    n_layers_mean: float                   # mean layers crossed per cut, the N of the 1/N bound
    vrr_ideal: float                       # 1 / n_layers_mean, the independent-layer bound
    efficiency: float                      # vrr_ideal / vrr, in (0, 1]; how much of the ideal was realised
    toe_apex_grade_delta: float            # percent Cu, toe minus apex; the segregation bias
    segregation_index: float               # toe-apex coarse-fraction delta, dimensionless
    mass_residual_t: float                 # deposited minus (in pile plus reclaimed); must be ~0


@dataclass(frozen=True)
class RunResult:
    """Everything one simulated build-and-reclaim produces."""

    case_id: str
    pad: PadSpec
    stacking: str
    reclaim: str
    dumps: list[TruckDump]
    cuts: list[ReclaimCut]
    height_final: list[float]              # nx*ny, row-major, metres
    coarse_final: list[float]              # nx*ny, row-major, surface coarse fraction
    grade_final: list[float]               # nx*ny, row-major, column tonnage-weighted percent Cu
    height_snapshots: list[dict]           # a handful of {t_s, h[]} frames for replay
    metrics: BlendMetrics
    starved: bool                          # True when reclaim outran stacking and the pile emptied
