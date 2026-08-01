"""The simulation driver: build a pile, reclaim it, and measure what the blending was worth.

This is the function the offline pipeline calls per case and the TypeScript live engine mirrors per
slider move. Everything it does is a pure function of ``(RunConfig, seed)``, which is what makes a
committed trace replayable (ADR-0054) and what lets the cross-lane test assert that the browser and
the pipeline agree.

The interleaving is deliberate. Real stacking and reclaiming happen at the same time, on opposite
ends of the pile, and a simulator that stacks the whole pile and only then reclaims it would produce a
different, easier problem: every cut would see every layer. Here reclaim starts once the pile holds
``start_fraction`` of its planned tonnage, and from then on both run together. That is also what makes
the starvation control C03 possible at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import blending, stacking
from .pile import Pile
from .schema import BlendMetrics, PadSpec, ReclaimCut, RunResult, TruckDump
from .stream import cumulative_tonnes

RECLAIM_METHODS: tuple[str, ...] = ("fullface", "bucketwheel", "end", "loader")

RECLAIM_LABELS: dict[str, str] = {
    "fullface": "Full-face bench",
    "bucketwheel": "Bucket-wheel pass",
    "end": "End reclaim",
    "loader": "Front-end loader",
}

N_SNAPSHOTS = 24


@dataclass(frozen=True)
class RunConfig:
    """Everything that determines a run, and therefore everything the App may expose as a control.

    A control that is not in this object cannot change the result, and ADR-0017 makes shipping such a
    control a defect. So this dataclass is also the definition of the App's control set.
    """

    #: the consumer's label for this run. The engine never interprets it, it only carries it
    #: through to the result so an application can key its artifacts by it.
    case_id: str = ""
    pad: PadSpec = field(default_factory=PadSpec)
    stacking: str = "chevron"
    reclaim: str = "fullface"
    n_passes: int = 24                 # stacker passes, that is, layers, the N of the 1/N bound
    sr: float = 1.0                    # Gray-Thornton segregation number, eq (3.19); 0 disables it
    reclaim_rate: float = 1.0          # reclaim tonnage per unit of stacked tonnage
    start_fraction: float = 0.35       # fraction of the build stacked before reclaim starts
    cut_tonnes: float = 900.0          # tonnes per reclaim cut
    seed: int = 42


def _mass_residual(pile: Pile) -> float:
    return pile.deposited_t - (pile.in_pile_t + pile.reclaimed_t)


def simulate(cfg: RunConfig, dumps: list[TruckDump]) -> RunResult:
    """Run one full build-and-reclaim and return the trace plus the measured blending.

    The reclaim front advances along the pad rather than sitting still, because a reclaimer that never
    moves would eat a hole through one station and then starve while the rest of the pile stands
    untouched. Advancing it is what makes the four reclaim geometries differ in the way the literature
    describes.
    """
    pad = cfg.pad
    pile = Pile(pad)
    n = len(dumps)
    if n == 0:
        raise ValueError("simulate needs at least one dump")

    positioned: list[TruckDump] = []
    for k, d in enumerate(dumps):
        x, y = stacking.dump_position(cfg.stacking, k, n, nx=pad.nx, ny=pad.ny,
                                      cell_m=pad.cell_m, n_passes=cfg.n_passes)
        positioned.append(TruckDump(d.event_id, d.t_s, d.truck_id, d.source_id, d.tonnes,
                                    d.grade_cu_pct, d.grade_au_gpt, d.coarse_frac,
                                    d.moisture_pct, x, y))

    total_t = sum(d.tonnes for d in positioned)
    start_t = cfg.start_fraction * total_t
    cuts: list[ReclaimCut] = []
    snapshots: list[dict] = []
    snap_every = max(1, n // N_SNAPSHOTS)

    stacked = 0.0
    reclaim_debt = 0.0
    front = 0
    cut_id = 0
    starved = False

    for k, d in enumerate(positioned):
        pile.deposit(d, sr=cfg.sr)
        stacked += d.tonnes

        if stacked >= start_t:
            reclaim_debt += d.tonnes * cfg.reclaim_rate
            while reclaim_debt >= cfg.cut_tonnes:
                cut, front = pile.reclaim(cut_id=cut_id, t_s=d.t_s, target_t=cfg.cut_tonnes,
                                          method=cfg.reclaim, front=front)
                if cut is None:
                    # the machine walked the whole pad and found nothing: the pile is empty and the
                    # reclaimer is starved, which is the C03 boundary rather than an error
                    starved = True
                    reclaim_debt = 0.0
                    break
                cuts.append(cut)
                cut_id += 1
                reclaim_debt -= cut.tonnes

        if k % snap_every == 0 or k == n - 1:
            snapshots.append({"t_s": d.t_s, "h": [round(v, 4) for v in pile.h]})

    # drain what is left, so the mass balance closes and the last layers are represented
    guard = 0
    while pile.in_pile_t > cfg.cut_tonnes and guard < pad.nx * 4:
        guard += 1
        cut, front = pile.reclaim(cut_id=cut_id, t_s=positioned[-1].t_s + guard * 60.0,
                                  target_t=cfg.cut_tonnes, method=cfg.reclaim, front=front)
        if cut is None:
            break
        cuts.append(cut)
        cut_id += 1

    metrics = measure(pile, positioned, cuts, cfg)
    return RunResult(
        case_id=cfg.case_id, pad=pad, stacking=cfg.stacking, reclaim=cfg.reclaim,
        dumps=positioned, cuts=cuts,
        height_final=[round(v, 4) for v in pile.h],
        coarse_final=[round(pile.surface_coarse(c), 4) for c in range(pad.n_cells)],
        grade_final=[round(pile.column_grade(c), 4) for c in range(pad.n_cells)],
        height_snapshots=snapshots, metrics=metrics, starved=starved,
    )


def measure(pile: Pile, dumps: list[TruckDump], cuts: list[ReclaimCut], cfg: RunConfig) -> BlendMetrics:
    """Compute the blending metrics for a finished run, on a tonnage base throughout.

    Every number here is reported in the product WITH the formula that produced it, because the VRR
    convention is reciprocal-ambiguous in the literature and a bare ratio is not self-describing.
    """
    in_vals = [d.grade_cu_pct for d in dumps]
    in_w = [d.tonnes for d in dumps]
    out_vals = [c.grade_cu_pct for c in cuts]
    out_w = [c.tonnes for c in cuts]

    var_in = blending.tonnage_weighted_variance(in_vals, in_w)
    var_out = blending.tonnage_weighted_variance(out_vals, out_w) if cuts else 0.0
    mean_in = blending.tonnage_weighted_mean(in_vals, in_w)
    mean_out = blending.tonnage_weighted_mean(out_vals, out_w) if cuts else 0.0
    achieved = blending.vrr(var_in, var_out)

    n_layers = (sum(c.n_layers * c.tonnes for c in cuts) / sum(out_w)) if cuts else 0.0
    ideal = blending.vrr_ideal(n_layers)
    eff = blending.blending_efficiency(achieved, n_layers)

    toe, apex = pile.toe_apex_split()
    if toe and apex:
        g_toe = sum(pile.column_grade(c) for c in toe) / len(toe)
        g_apex = sum(pile.column_grade(c) for c in apex) / len(apex)
        c_toe = sum(pile.column_coarse(c) for c in toe) / len(toe)
        c_apex = sum(pile.column_coarse(c) for c in apex) / len(apex)
        d_grade, d_coarse = g_toe - g_apex, c_toe - c_apex
    else:
        d_grade = d_coarse = 0.0

    return BlendMetrics(
        var_in=var_in, var_out=var_out, vrr=achieved, mean_in=mean_in, mean_out=mean_out,
        n_layers_mean=n_layers, vrr_ideal=ideal, efficiency=eff,
        toe_apex_grade_delta=d_grade, segregation_index=d_coarse,
        mass_residual_t=_mass_residual(pile),
    )


def input_variogram(dumps: list[TruckDump], n_lags: int = 20) -> dict:
    """Experimental variogram of the incoming stream, in cumulative tonnes."""
    centres, gamma, counts = blending.experimental_variogram(
        [d.grade_cu_pct for d in dumps], cumulative_tonnes(dumps), n_lags=n_lags)
    return {"lag_t": centres, "gamma": gamma, "pairs": counts,
            "model": blending.fit_spherical(centres, gamma, counts)}


def output_variogram(cuts: list[ReclaimCut], n_lags: int = 20) -> dict:
    """Experimental variogram of the reclaimed stream, on the same cumulative-tonnage base."""
    if len(cuts) < 4:
        return {"lag_t": [], "gamma": [], "pairs": [], "model": {}}
    pos: list[float] = []
    acc = 0.0
    for c in cuts:
        acc += c.tonnes
        pos.append(acc)
    centres, gamma, counts = blending.experimental_variogram(
        [c.grade_cu_pct for c in cuts], pos, n_lags=n_lags)
    return {"lag_t": centres, "gamma": gamma, "pairs": counts,
            "model": blending.fit_spherical(centres, gamma, counts)}
