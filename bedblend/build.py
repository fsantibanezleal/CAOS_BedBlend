"""The build: trucks, a plan, a dozer and a growing pile, driven end to end.

THIS IS WHERE THE PIECES BECOME A SYSTEM. Every other module here does one thing correctly in
isolation. This one runs the loop that the sources actually describe, and the loop is the product:

    for each area, for each bench:
        PADDOCK CAMPAIGN   heaps on the row lattice, building the base layer on the current floor
        DOZER              level it into a working floor, form the crest, raise the berm
        EDGE CAMPAIGN      radial sweeps, each load cascading over the face it is aimed at
    then RECLAIM           a sequenced face, cutting the lifts back out

quoting the specification it implements: "In a heaped fill stockpiling scenario, dumping occurs in two
phases. The first phase is a series of paddock dumps to form the base layer of the stockpile. The
second phase involves building an upper layer above an area of the paddock dumps from which a campaign
of edge dumps occurs until the bench is completed" (Young and Rogers, Minerals 2021, 11, 636).

WHAT MAKES THIS DIFFERENT FROM A SEQUENCE OF FUNCTION CALLS. Three couplings that the previous engine
did not have, and could not have had:

  * The pile constrains itself. Every load is routed over the trafficable surface AS IT IS NOW. A tip
    the pile has grown over is REFUSED and recorded as refused, rather than being served anyway.
  * The face decides the shape. The dump profile is chosen from the truck's measured distance to the
    live crest, and oriented along the crest normal, so the deposit geometry is an output of the build
    state rather than a setting.
  * The ledger follows the material. Every operation that moves material, deposition, relaxation,
    dozing and reclaim alike, carries the block ledger with it, and the invariant is checked.

DETERMINISM. Everything stochastic comes from one seeded stream, so a build is reproducible bit for
bit. The only stochastic choice in the whole build is which of the three at-crest profiles forms, and
that is drawn from their measured frequencies because the source is explicit that position alone does
not determine it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .blocks import BlockModel, transfer_distances
from .design import DumpPlan, Phase, TipPosition
from .dozer import DozerPass, build_berm, level, push_to_crest
from .dump import (
    DumpProfile,
    Placement,
    classify,
    place_edge,
    place_paddock,
    run_out_for_bench,
)
from .relax import relax_to, settle
from .terrain import Terrain
from .truck import Fleet, NoRoute, Payload, Route, reachable_mask


class _Rand:
    """A seeded xorshift, so a build is reproducible bit for bit.

    Deliberately not ``random``: the browser mirror of this engine has to produce the identical
    sequence, and a language's built-in generator is not a portable contract.
    """

    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        self.state = (seed | 1) & 0xFFFFFFFF

    def next(self) -> float:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state / 0x100000000


@dataclass
class LoadRecord:
    """One truck load, from dispatch to placement. This is the product's event log.

    A refused load is recorded with ``placed=False`` and its reason. Refusals are not failures to be
    hidden: they are the model reporting that the plan asked for something the pile no longer allows,
    and the count of them is a real measure of how good the dump plan was.
    """

    seq: int
    area: str
    bench: int
    phase: Phase
    truck_id: int
    x_m: float
    y_m: float
    grade: float
    source_block: int
    placed: bool
    # WHERE THE PLAN ASKED FOR THE LOAD, against where the truck could actually stand. The gap between
    # the two is a real quantity: it is what a fleet-management export shows when planned and actual
    # dump locations are compared, and it measures how well the plan matched the site.
    planned_x_m: float = 0.0
    planned_y_m: float = 0.0
    spot_offset_m: float = 0.0
    profile: DumpProfile | None = None
    distance_to_crest_m: float = 0.0
    heading_rad: float = 0.0
    length_m: float = 0.0
    width_m: float = 0.0
    max_thickness_m: float = 0.0
    approach: Route | None = None
    departure: Route | None = None
    refused_reason: str = ""


@dataclass
class BuildResult:
    """Everything the build produced, for the app and for the tests."""

    terrain: Terrain
    model: BlockModel
    loads: list[LoadRecord] = field(default_factory=list)
    dozer_passes: list[DozerPass] = field(default_factory=list)

    @property
    def placed(self) -> list[LoadRecord]:
        return [r for r in self.loads if r.placed]

    @property
    def refused(self) -> list[LoadRecord]:
        return [r for r in self.loads if not r.placed]

    @property
    def refusal_rate(self) -> float:
        return len(self.refused) / len(self.loads) if self.loads else 0.0

    def profile_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.placed:
            if r.profile is not None:
                out[r.profile.value] = out.get(r.profile.value, 0) + 1
        return out


def build(
    terrain: Terrain,
    plan: DumpPlan,
    fleet: Fleet,
    payloads: list[Payload],
    *,
    repose_deg: float = 37.0,
    face_angle_deg: float | None = None,
    seed: int = 20260801,
    crest_drop_m: float = 1.0,
    max_spot_offset_m: float = 25.0,
    verify_every: int = 0,
) -> BuildResult:
    """Run the whole plan, load by load, and return what happened.

    ``payloads`` is the incoming stream in arrival order. Its autocorrelation should come from a dig
    sequence rather than from a variogram parameter: consecutive trucks come from the same dig block,
    which is what makes consecutive loads correlated. This function does not generate it, because how
    the pit is dug is a property of the operation, not of the pile.

    ``face_angle_deg`` defaults to the repose angle, which is what a tipped face stands at.

    ``verify_every`` checks the ledger against the terrain every N loads. Off by default because it is
    O(cells) per check, on in the tests, and worth turning on whenever a build looks wrong.
    """
    # The shovel is in the pit, not on the stockpile. Placing it inside a dump area is a caller error
    # that otherwise shows up as every load after the first being refused, because the first load
    # buries the loading point and nothing can leave it again. Say so plainly instead.
    sx, sy = fleet.shovel_xy
    inside = plan.area_at(sx, sy)
    if inside is not None:
        raise ValueError(
            f"the shovel at ({sx}, {sy}) is inside dump area {inside.name!r}. The first load placed "
            f"there will bury the loading point and every later load will be refused for having no "
            f"drivable start. Put the shovel outside every area's footprint."
        )

    face_deg = face_angle_deg if face_angle_deg is not None else repose_deg
    model = BlockModel.over(terrain)
    rng = _Rand(seed)
    result = BuildResult(terrain=terrain, model=model)

    truck_spec = fleet.trucks[0].spec
    load_volume = truck_spec.load_volume_m3
    seq = 0
    since_dozer = 0

    for area in plan.areas:
        prev_top = 0.0
        for bench in sorted(area.benches, key=lambda b: b.index):
            # A bench's run-out depends on ITS OWN height, not on how high its top sits above the
            # pad. The second lift of a two-lift pile cascades over its own face, not over both.
            bench_height = max(bench.top_m - prev_top, 1e-6)
            prev_top = bench.top_m
            run_out = run_out_for_bench(bench_height, face_deg)
            tips = plan.bench_program(
                area, bench, load_volume_m3=load_volume, run_out_m=run_out
            )

            for tip in tips:
                if seq >= len(payloads):
                    break
                payload = payloads[seq]
                truck = fleet.trucks[seq % len(fleet.trucks)]

                crest = terrain.crest_cells(min_drop_m=crest_drop_m)
                # Reachability for the WHOLE pad, once per load. Asking it per candidate spot with a
                # route solve each time took a build from 40 s past 500 s.
                reachable = reachable_mask(terrain, fleet.shovel_xy, fleet.max_grade)
                rec = _run_one_load(
                    terrain, model, fleet, truck, tip, payload, crest, reachable,
                    rng=rng, run_out_m=run_out, repose_deg=repose_deg,
                    bench_index=bench.index, seq=seq, max_offset_m=max_spot_offset_m,
                )
                result.loads.append(rec)
                seq += 1

                if not rec.placed:
                    continue

                since_dozer += 1
                if since_dozer >= plan.loads_per_dozer_pass:
                    since_dozer = 0
                    result.dozer_passes.extend(
                        _doze(terrain, model, area, crest_drop_m, repose_deg)
                    )

                if verify_every and seq % verify_every == 0:
                    model.assert_consistent(terrain)

            # The bench is finished, so level what is left and form the floor the next bench starts
            # from. Without this the next paddock campaign would be laid on an unfinished surface.
            result.dozer_passes.extend(_doze(terrain, model, area, crest_drop_m, repose_deg))

    model.assert_consistent(terrain)
    return result


def _run_one_load(
    terrain: Terrain,
    model: BlockModel,
    fleet: Fleet,
    truck,
    tip: TipPosition,
    payload: Payload,
    crest: list[int],
    reachable: list[bool],
    *,
    rng: _Rand,
    max_offset_m: float,
    run_out_m: float,
    repose_deg: float,
    bench_index: int,
    seq: int,
) -> LoadRecord:
    """Dispatch, spot, place, settle, depart. One complete cycle."""
    base = LoadRecord(
        seq=seq, area=tip.area, bench=bench_index, phase=tip.phase, truck_id=truck.truck_id,
        x_m=tip.x_m, y_m=tip.y_m, grade=payload.grade, source_block=payload.source_block,
        placed=False, planned_x_m=tip.x_m, planned_y_m=tip.y_m,
    )

    # THE PLAN PROPOSES, THE SITE DISPOSES. A planned tip often cannot be occupied, and the reason is
    # physical rather than incidental: freshly placed material stands at its angle of repose, 37
    # degrees here, while a haul truck works to roughly 27. Measured directly, every single cell of a
    # settled heap is undrivable. A truck therefore never stands on fresh material; it stands on
    # levelled floor or original ground and tips ONTO the heap.
    #
    # So an unreachable tip is not an immediate refusal. The operator spots at the nearest workable
    # point instead, which is exactly what happens on site, where "dozer operators determine how haul
    # trucks access the dump or stockpile and in what order". The deviation is recorded, because the
    # gap between planned and actual dump locations is real, is what a fleet-management export shows,
    # and is a genuine measure of how good the plan was.
    actual = _nearest_reachable(terrain, tip, reachable, max_offset_m)
    if actual is None:
        base.refused_reason = (
            f"no drivable ground within {max_offset_m:.0f} m of the planned tip: the pile has grown "
            f"over its own access here"
        )
        return base
    try:
        heading, d_crest = fleet.dispatch(terrain, truck, actual, payload, crest=crest)
    except NoRoute as e:
        base.refused_reason = str(e)
        return base

    base.x_m, base.y_m = actual.x_m, actual.y_m
    base.spot_offset_m = math.hypot(actual.x_m - tip.x_m, actual.y_m - tip.y_m)

    dx, dy = truck.discharge_xy()

    # Which operator runs is decided by the terrain, not by the plan's label. A tip nominally in the
    # edge campaign that has no face in front of it is a heap, because that is what the material does.
    at_face = tip.phase is Phase.EDGE and d_crest <= 3.0 * terrain.cell_m * 4.0
    if at_face:
        profile = classify(d_crest, truck.spec, rand=rng.next())
        pl: Placement = place_edge(
            terrain, dx, dy, truck.spec.load_volume_m3, truck.spec,
            profile=profile, run_out_m=run_out_m,
            normal=(math.cos(heading), math.sin(heading)), distance_to_crest_m=d_crest,
        )
    else:
        pl = place_paddock(terrain, dx, dy, heading, truck.spec.load_volume_m3, truck.spec)

    if not pl.cells:
        base.refused_reason = "the load had nowhere to land on the pad"
        return base

    model.record(
        terrain, pl.cells, pl.added_m,
        grade=payload.grade, source_block=payload.source_block, event_id=seq,
        lift=bench_index, area=tip.area, grade_uncertainty=payload.grade_uncertainty,
    )

    # Emplaced steep, then settled. Both stages move material, so both carry the ledger.
    moves = settle(terrain, repose_deg, active=set(pl.cells))
    _carry(model, terrain, moves)

    fleet.depart(terrain, truck)

    base.placed = True
    base.profile = pl.profile
    base.distance_to_crest_m = d_crest
    base.heading_rad = pl.heading_rad
    base.length_m = pl.length_m
    base.width_m = pl.width_m
    base.max_thickness_m = pl.max_thickness_m
    base.approach = truck.approach
    base.departure = truck.departure
    return base


def _nearest_reachable(
    terrain: Terrain, tip: TipPosition, reachable: list[bool], max_offset_m: float
) -> TipPosition | None:
    """The closest spot to the planned tip that the truck can actually get to, or None.

    The plan is always tried first, so a feasible plan is followed exactly. Otherwise the search
    walks outward over cells the flood fill already marked reachable, which costs a bounded scan
    rather than one route solve per candidate.
    """
    c0 = terrain.cell_at(tip.x_m, tip.y_m)
    if c0 is not None and reachable[c0]:
        return tip

    r_cells = max(1, int(max_offset_m / terrain.cell_m))
    i0, j0 = terrain.ij(c0) if c0 is not None else (0, 0)
    best: tuple[float, int] | None = None
    for dj in range(-r_cells, r_cells + 1):
        j = j0 + dj
        if not (0 <= j < terrain.ny):
            continue
        for di in range(-r_cells, r_cells + 1):
            i = i0 + di
            if not (0 <= i < terrain.nx):
                continue
            c = terrain.idx(i, j)
            if not reachable[c]:
                continue
            x, y = terrain.xy(c)
            d = math.hypot(x - tip.x_m, y - tip.y_m)
            if d <= max_offset_m and (best is None or d < best[0]):
                best = (d, c)
    if best is None:
        return None
    x, y = terrain.xy(best[1])
    return TipPosition(x, y, tip.heading_rad, tip.phase, tip.area, tip.bench, tip.seq)


def _doze(
    terrain: Terrain, model: BlockModel, area, crest_drop_m: float, repose_deg: float
) -> list[DozerPass]:
    """A dozer visit: level the floor, push material out over the face, raise the berm.

    Each operation carries the ledger, and the surface is relaxed afterwards, because a blade leaves
    material standing steeper than it can hold.
    """
    out: list[DozerPass] = []

    p = level(terrain, area)
    if p.transfers:
        model.apply_transfers(p.transfers, distances=transfer_distances(terrain, p.transfers))
        out.append(p)

    crest = terrain.crest_cells(min_drop_m=crest_drop_m)
    if crest:
        nx_, ny_ = terrain.outward_normal(crest[len(crest) // 2])
        if abs(nx_) > 1e-12 or abs(ny_) > 1e-12:
            q = push_to_crest(terrain, area, normal=(nx_, ny_), depth_m=0.2, push_m=15.0)
            if q.transfers:
                model.apply_transfers(q.transfers, distances=transfer_distances(terrain, q.transfers))
                out.append(q)
        b = build_berm(terrain, crest, height_m=0.4, source_depth_m=0.1)
        if b.transfers:
            model.apply_transfers(b.transfers, distances=transfer_distances(terrain, b.transfers))
            out.append(b)

    _carry(model, terrain, relax_to(terrain, repose_deg))
    return out


def _carry(model: BlockModel, terrain: Terrain, moves: list[tuple[int, int, float]]) -> None:
    """Apply relaxation transfers to the ledger.

    Relaxation transfers are thicknesses; the ledger takes volumes. Getting that conversion wrong is
    silent and catastrophic, which is why it lives in exactly one place.
    """
    if not moves:
        return
    model.apply_transfers(
        [(a, b, v * model.cell_area_m2) for a, b, v in moves],
        distances=transfer_distances(terrain, moves),
    )


