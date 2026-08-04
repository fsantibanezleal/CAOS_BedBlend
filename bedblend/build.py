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
from collections.abc import Callable
from dataclasses import dataclass, field

from .blocks import BlockModel, transfer_distances
from .design import DumpPlan, Phase, TipPosition
from .dozer import DozerPass, build_berm, build_ramp, level, push_to_crest
from .dump import (
    DumpProfile,
    Placement,
    classify,
    place_edge,
    place_paddock,
    run_out_for_bench,
)
from .facesegregation import segregate_face
from .material import DEFAULT_MATERIAL, Material, SizeSplit
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
    # How strongly this load sorted itself on the way down the face, the drop it fell, and the coarse
    # fraction that rolled beyond the toe. Zero for a paddock heap, which has no face to sort along.
    segregation_index: float = 0.0
    overrun_fraction: float = 0.0
    drop_m: float = 0.0
    refused_reason: str = ""


@dataclass
class BuildResult:
    """Everything the build produced, for the app and for the tests."""

    terrain: Terrain
    model: BlockModel
    loads: list[LoadRecord] = field(default_factory=list)
    dozer_passes: list[DozerPass] = field(default_factory=list)
    # SURFACE SNAPSHOTS THROUGH THE BUILD, so the pile can be watched growing rather than only
    # inspected once finished. Each entry is (sequence number of the load just placed, loads placed
    # so far, a copy of the surface). The SEQUENCE number matters as much as the count: it is what
    # lets a player show the truck that is working right now instead of every path ever driven.
    snapshots: list[tuple[int, int, list[float]]] = field(default_factory=list)

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
    # How much of a bench goes down as paddock base layer before the edge campaign starts. The base
    # layer is ONE lift of heaps, a couple of metres over the footprint, which against a tall bench is
    # a small fraction of its volume. Setting it too high starves the edge campaign: the load budget
    # is consumed in paddock dumps and no face is ever formed to cascade over, so none of the cascade
    # physics runs at all.
    paddock_frac: float = 0.18,
    # How many placed loads between surface snapshots. Zero disables them. A snapshot is one float
    # per cell, so a couple of dozen keeps the artifact small while still animating the build.
    snapshot_every: int = 0,
    material: Material = DEFAULT_MATERIAL,
    route: Callable[[Payload], str] | None = None,
    verify_every: int = 0,
    after_load: Callable[[int, Terrain, BlockModel], None] | None = None,
) -> BuildResult:
    """Run the whole plan, load by load, and return what happened.

    ``payloads`` is the incoming stream in arrival order. Its autocorrelation should come from a dig
    sequence rather than from a variogram parameter: consecutive trucks come from the same dig block,
    which is what makes consecutive loads correlated. This function does not generate it, because how
    the pit is dug is a property of the operation, not of the pile.

    ``face_angle_deg`` defaults to the repose angle, which is what a tipped face stands at.

    ``material`` supplies the properties that are NOT constants of the engine: the density through
    the handling chain, the moisture that moves the angle of repose, and the size split that
    segregation acts on. A model with one size per load cannot segregate at all.

    ``route`` maps a load to the NAME of the area it belongs in, from its ore-control estimate. With
    it, several areas are under construction at once and a class ends up where it was sent. Without
    it, areas are worked one at a time. Routing is the mechanism by which sectors come to exist at
    all, so a yard with no router has one sector and nothing to compare.

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

    # EVERY AREA GETS A QUEUE OF PLANNED WORK, and the queues are consumed in one of two orders.
    #
    # Without a router the areas are worked one at a time, which is the single-stock case.
    # With one, each load is sent to the area its declared class routes it to and several areas are
    # under construction simultaneously. That is what an operation actually does: "the low SMR ore was
    # sent to one stockpile and the high SMR ore was sent to another stockpile. One high SMR stockpile
    # and one low SMR stockpile were built at a time" (Neufeld, Lyall and Deutsch, CCG Report 8 paper
    # 306, 2006). The routing decision is made from the ESTIMATE and before placement, so a
    # misclassified load lands in the wrong pile and stays there, which is a real and reportable
    # outcome rather than something to correct after the fact.
    queues: dict[str, list[tuple[TipPosition, float, int]]] = {}
    for area in plan.areas:
        q: list[tuple[TipPosition, float, int]] = []
        prev_top = 0.0
        for bench in sorted(area.benches, key=lambda b: b.index):
            # A bench's run-out depends on ITS OWN height, not on how high its top sits above the
            # pad. The second lift of a two-lift pile cascades over its own face, not over both.
            bench_height = max(bench.top_m - prev_top, 1e-6)
            prev_top = bench.top_m
            run_out = run_out_for_bench(bench_height, face_deg)
            for tip in plan.bench_program(
                area, bench, load_volume_m3=load_volume, run_out_m=run_out,
                paddock_frac=paddock_frac,
            ):
                q.append((tip, run_out, bench.index))
        queues[area.name] = q

    cursors: dict[str, int] = {name: 0 for name in queues}
    dozer_counts: dict[str, int] = {name: 0 for name in queues}
    last_doze: dict[str, int] = {name: -999 for name in queues}
    full_counts: dict[str, int] = {name: 0 for name in queues}
    order = [a.name for a in plan.areas]

    for payload in payloads:
        if route is not None:
            name = route(payload)
            if name not in queues:
                raise KeyError(
                    f"the router sent a load to area {name!r}, which is not in the plan; "
                    f"the plan has {order}"
                )
        else:
            # Sequential: finish an area's whole programme before starting the next.
            name = next((n for n in order if cursors[n] < len(queues[n])), order[-1])

        if cursors[name] >= len(queues[name]):
            # This area's programme is complete. A routed load with nowhere left to go is recorded as
            # refused rather than silently redirected, because redirecting it would quietly break the
            # one guarantee routing exists to provide: that a class ends up where it was sent.
            result.loads.append(
                LoadRecord(
                    seq=seq, area=name, bench=-1, phase=Phase.PADDOCK, truck_id=-1,
                    x_m=0.0, y_m=0.0, grade=payload.grade, source_block=payload.source_block,
                    placed=False,
                    refused_reason=f"area {name!r} is built out; its planned programme is complete",
                )
            )
            seq += 1
            continue

        tip, run_out, bench_index = queues[name][cursors[name]]
        cursors[name] += 1
        area = plan.area(name)
        truck = fleet.trucks[seq % len(fleet.trucks)]

        crest = terrain.crest_cells(min_drop_m=crest_drop_m)
        # Reachability for the WHOLE pad, once per load. Asking it per candidate spot with a route
        # solve each time took a build from 40 s past 500 s.
        reachable = reachable_mask(terrain, fleet.shovel_xy, fleet.max_grade)
        rec = _run_one_load(
            terrain, model, fleet, truck, tip, payload, crest, reachable,
            rng=rng, run_out_m=run_out, repose_deg=repose_deg,
            bench_index=bench_index, seq=seq, area=area, max_offset_m=max_spot_offset_m,
            material=material, face_deg=face_deg,
        )
        # THE DOZER IS STATIONED AT THE TIP HEAD, and a truck that finds no way in waits for it
        # rather than driving away. Access was being maintained only on the periodic pass, once every
        # hundred loads. A hundred paddock dumps is a field of three-metre cones standing at repose,
        # which no truck crosses, so the area sealed itself off within a few loads of every pass and
        # stayed sealed until the next one. Measured: 1162 of 1320 planned tips refused for access
        # and the pile stalled at 2.6 m, while the SAME terrain came out fully reachable at the end,
        # because the closing pass levelled everything after the loads that needed it were gone.
        #
        # Reopening only the RAMP was not enough and the measurement said so plainly: identical
        # placed count, identical profile census, identical peak. The corridor was never the
        # blockage. What blocks a truck is the unlevelled floor, so the whole visit runs, and the
        # rate limit keeps a stretch of genuinely unreachable tips from dozing once per load.
        if not rec.placed and "no drivable ground" in rec.refused_reason and seq - last_doze[name] >= 2:
            last_doze[name] = seq
            passes = _doze(
                terrain, model, area, crest_drop_m, repose_deg, fleet.max_grade, access_only=True
            )
            if passes:
                result.dozer_passes.extend(passes)
                crest = terrain.crest_cells(min_drop_m=crest_drop_m)
                reachable = reachable_mask(terrain, fleet.shovel_xy, fleet.max_grade)
                rec = _run_one_load(
                    terrain, model, fleet, truck, tip, payload, crest, reachable,
                    rng=rng, run_out_m=run_out, repose_deg=repose_deg,
                    bench_index=bench_index, seq=seq, area=area,
                    max_offset_m=max_spot_offset_m, material=material, face_deg=face_deg,
                )

        result.loads.append(rec)
        seq += 1

        if not rec.placed:
            continue

        n_placed = len(result.placed)
        if snapshot_every and n_placed % snapshot_every == 0:
            result.snapshots.append((rec.seq, n_placed, list(terrain.z)))

        # The dozer cadence is PER AREA. With several areas in progress a single global counter would
        # doze whichever area happened to receive the hundredth load, which is not how a machine
        # assigned to a dump area behaves.
        # THE CADENCE IS SPLIT, because the two kinds of blade work have very different costs and
        # very different urgency. Keeping the floor drivable and the road open is what decides
        # whether the NEXT load can be placed at all, and a field of fresh heaps stops being
        # crossable within a few loads; furnishing the tip head with a crest push and a safety berm
        # is periodic housekeeping. Running them together on one slow cadence meant access was
        # restored once every hundred loads and the ninety-nine in between were refused. Running
        # them together on a fast cadence meant the berm went up every twelve loads and ringed the
        # area. So: access often, furniture rarely.
        dozer_counts[name] += 1
        full_counts[name] += 1
        if dozer_counts[name] >= plan.loads_per_dozer_pass:
            dozer_counts[name] = 0
            full = full_counts[name] >= plan.loads_per_full_pass
            if full:
                full_counts[name] = 0
            result.dozer_passes.extend(
                _doze(terrain, model, area, crest_drop_m, repose_deg, fleet.max_grade,
                      access_only=not full)
            )

        # BUILD AND RECLAIM ARE NOT ALWAYS SEQUENTIAL. Some operations fill a pile and then take it
        # down; plenty of others feed and draw at the same time, and the two produce different piles
        # from the same ore because the material a cut crosses depends on how much of the campaign
        # had arrived when it was taken. The caller gets a hook after every placed load so it can run
        # a reclaim cut against the pile as it stands, rather than only against the finished one.
        if after_load is not None:
            after_load(len(result.placed), terrain, model)

        if verify_every and seq % verify_every == 0:
            model.assert_consistent(terrain)

    # Every area gets a closing pass, so the surface a reader sees is a finished floor rather than
    # whatever the last load happened to leave. ACCESS WORK ONLY: a berm is a windrow for a truck
    # reversing at a LIVE tip head, and a campaign that has finished does not have one. Raising a
    # wall around a completed pile is not what a dozer does, and it was the last operation before the
    # surface was checked, which made it the most expensive place to leave material standing.
    for area in plan.areas:
        result.dozer_passes.extend(
            _doze(terrain, model, area, crest_drop_m, repose_deg, fleet.max_grade, access_only=True)
        )

    if snapshot_every:
        result.snapshots.append((seq, len(result.placed), list(terrain.z)))

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
    area,
    material: Material = DEFAULT_MATERIAL,
    face_deg: float = 37.0,
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
    actual = _nearest_reachable(terrain, tip, reachable, max_offset_m, area)
    if actual is None:
        base.refused_reason = (
            f"no drivable ground inside area {area.name!r} within {max_offset_m:.0f} m of the "
            f"planned tip: the pile has grown over its own access here"
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

    # SIZE SEGREGATION, applied where it actually happens: down a face, not on a flat heap.
    # A cascading load sorts itself, coarse to the toe and fines toward the crest, more strongly from
    # a higher and steeper face. A paddock heap keeps the material's own split, because a load tipped
    # on flat ground has no face to sort along.
    split = SizeSplit.of(material.coarse_fraction)
    if at_face and pl.s_frac:
        drop = terrain.z[terrain.cell_at(dx, dy) or 0] - min(
            (terrain.z[c] for c in pl.cells), default=0.0
        )
        seg = segregate_face(drop_m=max(drop, 0.0), face_angle_deg=face_deg, mat=material)
        nb = seg.n_bins
        coarse = [
            seg.coarse_fraction_at(split, min(int(sv * nb), nb - 1)) for sv in pl.s_frac
        ]
        base.segregation_index = seg.intensity
        base.overrun_fraction = seg.overrun_fraction
        base.drop_m = max(drop, 0.0)
    else:
        coarse = [split.coarse] * len(pl.cells)

    model.record(
        terrain, pl.cells, pl.added_m,
        grade=payload.grade, source_block=payload.source_block, event_id=seq,
        lift=bench_index, area=tip.area, grade_uncertainty=payload.grade_uncertainty,
        coarse_fraction=coarse,
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
    terrain: Terrain, tip: TipPosition, reachable: list[bool], max_offset_m: float, area
) -> TipPosition | None:
    """The closest spot to the planned tip that the truck can actually get to, or None.

    The plan is always tried first, so a feasible plan is followed exactly. Otherwise the search
    walks outward over cells the flood fill already marked reachable, which costs a bounded scan
    rather than one route solve per candidate.

    THE ALTERNATIVE SPOT MUST BE INSIDE THE DUMP AREA. Without that
    constraint the offset is just a licence to tip in the haul road: measured on the reference
    scenario, 284 of 402 placed loads landed outside their own area, the road silted up, the loading
    point was buried under material nobody planned to put there, and from that moment the flood fill
    returned nothing reachable anywhere on the pad and every remaining load was refused. A truck that
    cannot reach its tip is redirected to another tip in the same area or it is refused. It does not
    dump on the road, and neither does this.
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
            if not area.contains(x, y):
                continue
            d = math.hypot(x - tip.x_m, y - tip.y_m)
            if d <= max_offset_m and (best is None or d < best[0]):
                best = (d, c)
    if best is None:
        return None
    x, y = terrain.xy(best[1])
    return TipPosition(x, y, tip.heading_rad, tip.phase, tip.area, tip.bench, tip.seq)


def _doze(
    terrain: Terrain, model: BlockModel, area, crest_drop_m: float, repose_deg: float,
    max_grade: float = 0.5, *, access_only: bool = False,
) -> list[DozerPass]:
    """A dozer visit: level the floor, push material out over the face, raise the berm.

    Each operation carries the ledger, and the surface is relaxed afterwards, because a blade leaves
    material standing steeper than it can hold.

    ``access_only`` runs the two operations that OPEN THE ROAD and skips the two that furnish the
    tip head. The distinction is not cosmetic. A berm is a windrow at the crest for a reversing truck
    to feel, and it is by construction a wall; run it often enough and it rings the area. Measured:
    with the full visit on every access refusal the whole 1296-cell area came out unreachable at a
    peak of 3.2 m, and the peak DROPPED across the visit, from 3.53 to 3.21, because the blade was
    taking the crown to build the wall that was sealing the area. A truck waiting at the gate wants
    the ramp graded and the floor levelled. It does not want a berm.
    """
    out: list[DozerPass] = []

    # THE RAMP FIRST. Without it the reserved corridor is a trench between the pad and a working
    # level nothing can climb, and the build stalls with most of its planned tips refused.
    r = build_ramp(terrain, area, max_grade=max_grade)
    if r.transfers:
        model.apply_transfers(r.transfers, distances=transfer_distances(terrain, r.transfers))
        out.append(r)

    p = level(terrain, area)
    if p.transfers:
        model.apply_transfers(p.transfers, distances=transfer_distances(terrain, p.transfers))
        out.append(p)

    if access_only:
        _carry(model, terrain, relax_to(terrain, repose_deg))
        return out

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


