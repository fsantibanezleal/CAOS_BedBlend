"""Unit 9: sequenced reclaim from a real face.

Two things the previous engine got wrong are asserted here directly: a cut must relax what it
undercuts, and the machine must engage a face rather than an integer position.
"""
from __future__ import annotations

import itertools
import math

import pytest

from bedblend.blocks import BlockModel, transfer_distances
from bedblend.design import rectangular_yard
from bedblend.dump import place_paddock
from bedblend.reclaim import (
    Cut,
    ReclaimFace,
    ReclaimMethod,
    advance,
    campaign,
    cut,
    haul_cycle,
    next_cut,
)
from bedblend.relax import assert_stable, relax_to
from bedblend.terrain import Terrain, TruckSpec

REPOSE = 37.0
CELL = 2.5
# The gradient a laden haul truck climbs: two thirds of the repose angle, the same limit the build
# side uses, so a reclaim truck cannot drive anywhere a haul truck could not.
MAX_GRADE = math.tan(math.radians(REPOSE)) / 1.5


def _stocked(n_loads: int = 160):
    """A base layer with grades that rise along the build, so order of extraction matters."""
    # The pad has to hold the area PLUS its margin: `rectangular_yard` offsets areas from the origin
    # so a dump on the near edge has ground to cascade onto instead of running off the array.
    t = Terrain.flat(48, 48, CELL)
    plan = rectangular_yard(
        n_areas=1, area_width_m=60.0, area_length_m=60.0, bench_height_m=6.0, n_benches=1,
        margin_m=30.0,
    )
    plan.row_spacing_m = 8.0
    area = plan.areas[0]
    truck = TruckSpec()
    model = BlockModel.over(t)
    for k, tp in enumerate(plan.paddock_tips(area, area.benches[0])[:n_loads]):
        grade = 0.30 + 0.004 * k        # a clear trend, so LIFO and FIFO must differ
        pl = place_paddock(t, tp.x_m, tp.y_m, tp.heading_rad, truck.load_volume_m3, truck)
        model.record(
            t, pl.cells, pl.added_m,
            grade=grade, source_block=k // 20, event_id=k, lift=0, area=area.name,
        )
        # Relax after every load and carry the ledger with it. Relaxation MOVES MATERIAL, so a
        # ledger that is not told about it drifts away from the terrain, and every grade reported
        # afterwards is attached to the wrong place.
        moves = relax_to(t, REPOSE, active=set(pl.cells))
        if moves:
            model.apply_transfers(
                [(a, b, v * model.cell_area_m2) for a, b, v in moves],
                distances=transfer_distances(t, moves),
            )
    model.assert_consistent(t)
    return t, area, model


def _face(**kw) -> ReclaimFace:
    # The face starts at the area's near edge, which is the margin, not the pad origin.
    base = {
        "method": ReclaimMethod.FULL_HEIGHT, "position_m": 30.0, "direction": (1.0, 0.0),
        "depth_m": 10.0, "width_m": 200.0, "max_face_m": 15.0,
    }
    base.update(kw)
    return ReclaimFace(**base)


def test_a_cut_delivers_material_and_removes_it_from_the_pile():
    t, _area, model = _stocked()
    before = model.total_tonnes()
    c = cut(t, model, _face(), 2000.0, repose_deg=REPOSE)
    assert c.tonnes > 0
    assert model.total_tonnes() == pytest.approx(before - c.tonnes, rel=1e-6)
    assert 0.25 < c.grade < 1.0
    model.assert_consistent(t)


def test_a_cut_relaxes_what_it_undercuts():
    """v1 called the cascade only from deposit and never after reclaim, so a cut face could stand
    at any angle indefinitely."""
    t, _area, model = _stocked()
    cut(t, model, _face(depth_m=5.0), 3000.0, repose_deg=REPOSE)
    assert_stable(t, REPOSE)


def test_the_face_is_a_slab_not_a_point():
    """v1's reclaimer was a single integer front, and the stacker and reclaimer were measured
    occupying the same cell in 5 of 51 cuts."""
    t, _area, _model = _stocked()
    f = _face(depth_m=5.0, width_m=30.0)
    cells = f.engaged_cells(t)
    assert len(cells) > 1
    xs = [t.xy(c)[0] for c in cells]
    ys = [t.xy(c)[1] for c in cells]
    assert max(xs) - min(xs) <= 5.0 + CELL          # bounded by the cut depth
    assert max(ys) - min(ys) <= 30.0 + CELL         # bounded by the engaged width


def test_the_face_advances_in_order_and_eventually_runs_out():
    t, _area, _model = _stocked()
    f = _face(depth_m=10.0)
    positions = []
    for _ in range(40):
        positions.append(f.position_m)
        if not advance(f, t):
            break
    assert positions == sorted(positions), "the face went backwards"
    assert len(positions) < 40, "the face never reached the end of the pile"


def test_lifo_and_fifo_deliver_different_grades():
    """The extraction order is a real decision. If it does not change the feed, it is not modelled.

    Asserted with a face height SHORTER than the column, which is the only situation in which the
    order within a column can matter and is what ``max_face_m`` is for. The pile here is about six
    metres and the machine will cut fifteen, so a cut that is allowed its full lift takes the whole
    column and the three methods necessarily agree; that degeneracy is asserted directly below rather
    than left as a surprise.
    """
    t1, _a1, m1 = _stocked()
    t2, _a2, m2 = _stocked()
    c_lifo = cut(t1, m1, _face(method=ReclaimMethod.LIFO, max_face_m=3.0), 3000.0, repose_deg=REPOSE)
    c_fifo = cut(t2, m2, _face(method=ReclaimMethod.FIFO, max_face_m=3.0), 3000.0, repose_deg=REPOSE)
    assert c_lifo.tonnes == pytest.approx(c_fifo.tonnes, rel=1e-6)
    assert c_lifo.grade != pytest.approx(c_fifo.grade, rel=1e-6)


def test_a_full_column_cut_makes_the_order_within_it_irrelevant():
    """Taking a whole column top to bottom delivers the same material whichever end you start at.

    This is not a limitation, it is the arithmetic, and it is the reason the test above has to
    constrain the face height to see any difference at all. It is asserted because the previous
    engine's proportional skim never took a full column, so the degeneracy could not arise and its
    absence was mistaken for the extraction order always mattering.
    """
    grades = []
    for method in (ReclaimMethod.LIFO, ReclaimMethod.FIFO, ReclaimMethod.FULL_HEIGHT):
        t, _a, m = _stocked()
        # max_face_m well above the roughly six metre column, so every engaged cell is taken out.
        grades.append(cut(t, m, _face(method=method, max_face_m=50.0), 3000.0, repose_deg=REPOSE))
    assert all(c.tonnes > 0 for c in grades)
    for c in grades[1:]:
        assert c.tonnes == pytest.approx(grades[0].tonnes, rel=1e-9)
        assert c.grade == pytest.approx(grades[0].grade, rel=1e-9)


def test_provenance_sums_to_one_and_carries_its_displacement():
    t, _area, model = _stocked()
    c = cut(t, model, _face(), 2000.0, repose_deg=REPOSE)
    assert sum(c.provenance.values()) == pytest.approx(1.0, abs=1e-9)
    assert len(c.provenance) > 1, "a cut through several dig blocks reported only one source"
    # Undozed material has not moved, so the honest displacement is zero rather than unreported.
    assert c.displacement_m >= 0.0


def test_a_campaign_produces_a_feed_series_that_drains_the_pile():
    t, _area, model = _stocked()
    before = model.total_tonnes()
    cuts = campaign(
        t, model, _face(depth_m=10.0), cut_tonnes=1500.0, n_cuts=40, repose_deg=REPOSE
    )
    assert len(cuts) > 3
    delivered = sum(c.tonnes for c in cuts)
    assert delivered > 0
    assert model.total_tonnes() == pytest.approx(before - delivered, rel=1e-6)
    assert_stable(t, REPOSE)


def test_full_height_blends_more_than_lifo():
    """"processing the stockpile in parallel vertical approaches": a vertical cut mixes the lifts,
    a top-down cut does not. The blending method must show lower feed variance.

    Run with a face height SHORTER than the column, for the same reason
    `test_lifo_and_fifo_deliver_different_grades` is: a cut allowed its full lift takes the whole
    column, and then a vertical approach and a top-down one remove exactly the same material. The
    methods can only differ while there is column left above or below the cut, which is what
    `max_face_m` decides. With the full lift allowed the two variances agree to four significant
    figures, and that is the arithmetic rather than the blending failing.
    """
    def feed(method: ReclaimMethod) -> list[float]:
        t, _a, m = _stocked()
        cs = campaign(
            t, m, _face(method=method, depth_m=10.0, max_face_m=2.0),
            cut_tonnes=1500.0, n_cuts=20, repose_deg=REPOSE,
        )
        return [c.grade for c in cs if c.tonnes > 0]

    def var(xs: list[float]) -> float:
        if len(xs) < 2:
            return 0.0
        m = sum(xs) / len(xs)
        return sum((x - m) ** 2 for x in xs) / len(xs)

    fh, lifo = feed(ReclaimMethod.FULL_HEIGHT), feed(ReclaimMethod.LIFO)
    assert fh and lifo
    assert var(fh) <= var(lifo)


def test_an_empty_pile_yields_nothing_rather_than_inventing_material():
    t = Terrain.flat(30, 30, CELL)
    model = BlockModel.over(t)
    c = cut(t, model, _face(), 1000.0, repose_deg=REPOSE)
    assert isinstance(c, Cut)
    assert c.tonnes == 0.0


# ------------------------------------------------------------------------------------------------
# THE HAUL CYCLE. Reclaim used to remove material at a face and report a tonnage, with nothing coming
# for it: no truck, no route, no way off site. The pile lost volume and no machine was ever there.
# ------------------------------------------------------------------------------------------------


def _exit_of(t: Terrain) -> tuple[float, float]:
    """A point off the near edge of the pad, which is where the road meets the site."""
    return t.nx * t.cell_m / 2.0, 2.0


def test_a_cut_records_the_truck_that_came_for_it():
    t, _area, model = _stocked()
    cuts = campaign(
        t, model, _face(depth_m=10.0), cut_tonnes=1500.0, n_cuts=8, repose_deg=REPOSE,
        exit_xy=_exit_of(t), max_grade=MAX_GRADE,
    )
    served = [c for c in cuts if c.stand is not None]
    assert served, "not one cut had a truck routed to it"

    for c in served:
        # It came from the road and it went back to the road. The ends are cell CENTRES, because a
        # route is a walk over cells, so they sit within one cell of the point asked for.
        assert len(c.approach) >= 2
        assert len(c.departure) >= 2
        near = CELL * 1.5
        assert math.dist(c.approach[0], _exit_of(t)) <= near
        assert math.dist(c.approach[-1], c.stand) <= near
        assert math.dist(c.departure[0], c.stand) <= near
        assert math.dist(c.departure[-1], _exit_of(t)) <= near
        # The loader is ON the cut; the truck stands somewhere it can actually be.
        assert c.loader is not None
        # And the truck is not parked on top of the loader: it stands beside the face.
        assert math.dist(c.stand, c.loader) > 0.0


def test_the_truck_stands_on_drivable_ground_not_on_the_face():
    """A loader digs the face. A truck cannot stand on a face, and this is the whole reason the two
    positions are recorded separately."""
    from bedblend.truck import passable_mask

    t, _area, model = _stocked()
    cuts = campaign(
        t, model, _face(depth_m=10.0), cut_tonnes=1500.0, n_cuts=8, repose_deg=REPOSE,
        exit_xy=_exit_of(t), max_grade=MAX_GRADE,
    )
    mask = passable_mask(t, MAX_GRADE)
    for c in (x for x in cuts if x.stand is not None):
        cell = t.cell_at(*c.stand)
        assert mask[cell], "the truck was parked on ground it could not stand on"


def test_the_route_is_drivable_end_to_end():
    """Every step of both legs obeys the same per-step gradient rule the build side uses, so a
    reclaim truck cannot drive somewhere a haul truck could not.

    CHECKED AT THE MOMENT THE ROUTE WAS SOLVED, which means driving the campaign one cut at a time.
    A route is solved on the surface the cut just left, and the next cut relaxes that surface, so
    inspecting a finished campaign's routes against the final terrain asks whether a path driven an
    hour ago is drivable over ground that has since been dug away. That is not the invariant, and the
    version of this test that did it passed only because the discrepancies happened to be small.

    ON THE GRID PATH, NOT ON THE POLYLINE. `Route.points` collapses collinear runs, so consecutive
    points can be twenty cells apart while `step_ok` divides the rise by ONE cell width, reporting a
    gradient twentyfold too steep. `approach_cells` and `departure_cells` are the adjacent-cell path
    the rule is actually about.
    """
    from bedblend.truck import step_ok

    t, _area, model = _stocked()
    face = _face(depth_m=10.0)
    exit_xy = _exit_of(t)
    checked = 0
    served = 0
    for _ in range(6):
        c = next_cut(t, model, face, 1500.0, repose_deg=REPOSE)
        if c is None:
            break
        haul_cycle(t, c.cells, exit_xy=exit_xy, max_grade=MAX_GRADE).apply_to(c)
        if c.stand is None:
            continue
        served += 1
        for leg in (c.approach_cells, c.departure_cells):
            assert leg, "a served cut recorded a leg with no grid path behind it"
            for ca, cb in itertools.pairwise(leg):
                if ca == cb:
                    continue
                assert step_ok(t, ca, cb, MAX_GRADE), (
                    f"a leg steps from {t.xy(ca)} to {t.xy(cb)}, "
                    f"a rise of {abs(t.z[cb] - t.z[ca]):.2f} m, which no truck could climb"
                )
                checked += 1
    assert served > 0, "no cut was served, so the assertion proved nothing"
    assert checked > 0, "no route steps were checked, so the assertion proved nothing"


def test_a_parked_truck_does_not_get_the_tipping_exemption():
    """The last step onto the stand has to be climbable, because the truck is parking, not tipping.

    `solve_route` exempts the GOAL cell from the gradient rule so that a haul truck can spot at a
    crest and tip over the edge, which is the whole edge-dumping campaign. A reclaim truck routed to
    a loading stand is doing the opposite thing and should not inherit it.

    Stated plainly because the distinction matters: on these fixtures the exemption changes no route,
    since the stand is already picked from the passability mask and the flood fill. This pins the
    semantics so the case where it WOULD matter cannot regress; it is not the repair of a defect that
    was measured, and the docstring says so rather than implying otherwise.
    """
    from bedblend.truck import solve_route, step_ok

    t, _area, model = _stocked()
    face = _face(depth_m=10.0)
    exit_xy = _exit_of(t)
    c = next_cut(t, model, face, 1500.0, repose_deg=REPOSE)
    assert c is not None
    hc = haul_cycle(t, c.cells, exit_xy=exit_xy, max_grade=MAX_GRADE)
    assert hc.stand is not None

    strict = solve_route(t, exit_xy, hc.stand, max_grade=MAX_GRADE, strict_goal=True).cells
    assert step_ok(t, strict[-2], strict[-1], MAX_GRADE), "the strict route still ends unclimbably"
    # And the haul cycle is the one that asked for it.
    assert hc.approach is not None
    tail = hc.approach.cells
    assert step_ok(t, tail[-2], tail[-1], MAX_GRADE)


def test_without_an_exit_the_campaign_still_delivers_but_records_no_haulage():
    """The haulage is additive: omitting it changes no tonnage and no grade, which is what makes it
    safe to add to an engine other products already consume."""
    t1, _a1, m1 = _stocked()
    t2, _a2, m2 = _stocked()
    plain = campaign(t1, m1, _face(depth_m=10.0), cut_tonnes=1500.0, n_cuts=6, repose_deg=REPOSE)
    hauled = campaign(
        t2, m2, _face(depth_m=10.0), cut_tonnes=1500.0, n_cuts=6, repose_deg=REPOSE,
        exit_xy=_exit_of(t2), max_grade=MAX_GRADE,
    )
    assert [round(c.tonnes, 6) for c in plain] == [round(c.tonnes, 6) for c in hauled]
    assert [round(c.grade, 6) for c in plain] == [round(c.grade, 6) for c in hauled]
    assert all(c.stand is None for c in plain)
    assert any(c.stand is not None for c in hauled)


# ---------------------------------------------------------------------------------------------
# THE FOOTPRINT OF A CUT IS THE MACHINE'S, NOT THE FACE'S
# ---------------------------------------------------------------------------------------------
# The engine used to spread every cut proportionally over every cell of the working face, so the
# ground disturbed by a cut was the whole face no matter how little material came out of it.
# Measured on the shipped artifacts: 632 cuts, mean footprint 594 square metres, worst case the
# entire 900 square metre slab, and one scenario removing 355 tonnes while touching 486 of them.
# Nothing failed, because nothing measured the footprint. These do.


def test_the_footprint_of_a_cut_scales_with_the_tonnage_taken():
    """A small cut leaves a small hole. This is the defect, stated as a property."""
    small = cut(*_stocked()[::2], _face(), 300.0, repose_deg=REPOSE)  # type: ignore[misc]
    big = cut(*_stocked()[::2], _face(), 3000.0, repose_deg=REPOSE)  # type: ignore[misc]
    assert small.tonnes < big.tonnes
    assert len(small.cells) < len(big.cells), (
        f"a {small.tonnes:.0f} t cut touched {len(small.cells)} cells and a "
        f"{big.tonnes:.0f} t cut touched {len(big.cells)}: the footprint is not the machine's"
    )
    # And it is proportionate rather than merely ordered: ten times the tonnage from the same
    # ground cannot come out of a similar number of cells.
    assert len(big.cells) > 2 * len(small.cells)


def test_a_cut_never_reaches_outside_the_machines_dig_radius():
    """The hard bound. Whatever the tonnage asked for, the machine cannot dig what it cannot reach."""
    t, _a, m = _stocked()
    face = _face()
    # Ask for far more than the pile holds, so nothing but the reach limits the answer.
    sx, sy = face.stance(t)
    c = cut(t, m, face, 10_000_000.0, repose_deg=REPOSE)
    assert c.cells
    r = face.loader.dig_radius_m
    for cell in c.cells:
        x, y = t.xy(cell)
        d = math.hypot(x - sx, y - sy)
        assert d <= r + 1e-9, f"cell {cell} dug at {d:.1f} m from a stance with {r:.1f} m of reach"


def test_the_footprint_is_a_small_fraction_of_the_face_it_works():
    """The regression, in the terms it was found in: cells engaged against cells available."""
    t, _a, m = _stocked()
    face = _face()
    envelope = len(face.engaged_cells(t))
    c = cut(t, m, face, 900.0, repose_deg=REPOSE)
    assert c.tonnes > 0
    assert envelope > 0
    assert len(c.cells) < envelope / 3.0, (
        f"a {c.tonnes:.0f} t cut engaged {len(c.cells)} of {envelope} cells on the face"
    )


def test_the_machine_trams_along_the_face_instead_of_working_one_spot():
    """Successive cuts move. A campaign taken entirely from one stance is not a campaign."""
    t, _a, m = _stocked()
    face = _face()
    cuts = campaign(t, m, face, cut_tonnes=900.0, n_cuts=8, repose_deg=REPOSE)
    assert len(cuts) >= 4
    centres = {(round(_mid(t, c.cells)[0], 0), round(_mid(t, c.cells)[1], 0)) for c in cuts}
    assert len(centres) > 1, "every cut of the campaign came from the same place"


def _mid(t: Terrain, cells: list[int]) -> tuple[float, float]:
    xs = [t.xy(c)[0] for c in cells]
    ys = [t.xy(c)[1] for c in cells]
    return (sum(xs) / len(xs), sum(ys) / len(ys)) if cells else (0.0, 0.0)


def test_the_reclaimed_feed_carries_its_size_split():
    """`coarse_fraction` must survive the trip out of the pile, on every extraction order.

    It did not. `_take` rebuilt a split parcel positionally with nine of `Parcel`'s ten fields for
    both FIFO and FULL_HEIGHT, so every reclaimed parcel left with its coarse fraction zeroed. That
    is the same defect, in the same shape, as the one that put a 40 percent coarse deficit into a
    shipped release from `blocks.py`. Asserted for each method rather than for one.
    """
    for method in (ReclaimMethod.LIFO, ReclaimMethod.FIFO, ReclaimMethod.FULL_HEIGHT):
        t, _area, model = _stocked_with_coarse(0.42)
        c = cut(t, model, _face(method=method, max_face_m=3.0), 1200.0, repose_deg=REPOSE)
        assert c.tonnes > 0, method
        assert c.coarse_fraction == pytest.approx(0.42, abs=1e-6), (
            f"{method.value} delivered {c.tonnes:.0f} t at coarse fraction "
            f"{c.coarse_fraction:.4f} from a pile placed uniformly at 0.42"
        )


def _stocked_with_coarse(coarse: float, n_loads: int = 120):
    """The same pile, placed at a known uniform size split so the reclaimed split is checkable."""
    t = Terrain.flat(48, 48, CELL)
    plan = rectangular_yard(
        n_areas=1, area_width_m=60.0, area_length_m=60.0, bench_height_m=6.0, n_benches=1,
        margin_m=30.0,
    )
    plan.row_spacing_m = 8.0
    area = plan.areas[0]
    truck = TruckSpec()
    model = BlockModel.over(t)
    for k, tp in enumerate(plan.paddock_tips(area, area.benches[0])[:n_loads]):
        pl = place_paddock(t, tp.x_m, tp.y_m, tp.heading_rad, truck.load_volume_m3, truck)
        model.record(
            t, pl.cells, pl.added_m,
            grade=0.30 + 0.004 * k, source_block=k // 20, event_id=k, lift=0, area=area.name,
            coarse_fraction=[coarse] * len(pl.cells),
        )
        moves = relax_to(t, REPOSE, active=set(pl.cells))
        if moves:
            model.apply_transfers(
                [(a, b, v * model.cell_area_m2) for a, b, v in moves],
                distances=transfer_distances(t, moves),
            )
    return t, area, model


def test_a_face_that_outruns_a_growing_pile_goes_back_to_the_start():
    """A concurrent campaign reclaims a pile that is still being built.

    The face advances as it works, so it can run past the end of the material simply by being ahead
    of the trucks. Left parked out there every later cut finds nothing and the campaign stops without
    saying so: measured on the artifacts, the concurrent scenario fell from 28 cuts to 2 and the surge
    scenario from 74 to 2, both still producing a plausible-looking feed series from the few that got
    through. That is the worst shape a defect can take, so it is pinned here.
    """
    t, _area, model = _stocked()
    face = _face(depth_m=10.0)
    origin = face.position_m

    # Run the face off the end deliberately.
    for _ in range(200):
        if not advance(face, t):
            break
    assert face.position_m > origin, "the face never advanced"
    assert not advance(face, t), "the face should now be past the material"

    # A cut from out there finds nothing, and `next_cut` must recover rather than give up forever.
    assert cut(t, model, face, 1500.0, repose_deg=REPOSE).tonnes == 0.0
    c = next_cut(t, model, face, 1500.0, repose_deg=REPOSE)
    assert c is not None and c.tonnes > 0, (
        "a face that outran the pile never came back, so every later cut would find nothing"
    )
    assert face.position_m <= origin + face.depth_m * 3, "the face did not rewind toward its start"


def test_an_empty_pad_still_terminates():
    """The rewind must not turn an exhausted pile into an endless search."""
    t = Terrain.flat(48, 48, CELL)
    model = BlockModel.over(t)
    assert next_cut(t, model, _face(depth_m=10.0), 1500.0, repose_deg=REPOSE) is None


def test_a_thin_pile_delivers_a_short_cut_instead_of_being_swept():
    """The machine trams a stretch of face for one parcel, not the whole yard.

    A pile that cannot supply the tonnage asked for delivers a SHORT cut, which is the real
    operational answer. Assembling without a bound instead sweeps ground until the order is filled,
    and that is how a concurrent scenario reclaiming a pile that is still being built came out at
    3303 square metres per cut removing 0.31 m: a skim across most of the pad, dressed up as a full
    parcel. The bound only binds when the ground is thin, so a pile that CAN supply the tonnage still
    delivers all of it, which is asserted here too because a cap that always binds is just a smaller
    cut.
    """
    thin = Terrain.flat(48, 48, CELL)
    model = BlockModel.over(thin)
    # A shallow, wide layer: plenty of tonnage in total, almost none within any one working stretch.
    cells = [c for c in range(thin.n_cells)]
    thick = [0.4] * len(cells)
    for c, dz in zip(cells, thick):
        thin.z[c] += dz
    model.record(
        thin, cells, thick, grade=0.5, source_block=0, event_id=0, lift=0, area="flat",
    )
    face = ReclaimFace(
        method=ReclaimMethod.FULL_HEIGHT, position_m=0.0, direction=(1.0, 0.0),
        depth_m=10.0, width_m=120.0, max_face_m=15.0,
    )
    want = 100_000.0
    c = next_cut(thin, model, face, want, repose_deg=REPOSE)
    assert c is not None and c.tonnes > 0
    assert c.tonnes < want, "the cut filled an order the ground could not supply"
    swept = len(c.cells) * (CELL ** 2)
    sweep = max(2, math.ceil(face.width_m / (2.0 * face.loader.dig_radius_m)))
    disc = math.pi * face.loader.dig_radius_m ** 2
    assert swept <= (sweep + 1) * disc, (
        f"one cut swept {swept:.0f} m2, more than the {sweep + 1} working stances it is allowed"
    )

    # And the bound must not bite when the ground is deep enough to fill the order from one stretch.
    t, _a, m = _stocked()
    full = next_cut(t, m, _face(depth_m=10.0), 1500.0, repose_deg=REPOSE)
    assert full is not None
    assert full.tonnes == pytest.approx(1500.0, rel=1e-6), (
        "the tramming bound cut short an order the pile could fill"
    )


def test_the_truck_never_parks_on_the_ground_the_loader_is_digging():
    """Two machines cannot occupy one cell, and this engine exists partly because they used to.

    The stacker and the reclaimer were measured inside the same cell in 5 of 51 cuts in the previous
    version. The exclusion was invisible while a cut spread over the whole face, because the centroid
    of a 594 square metre skim was never a cell a truck would pick; once the bite became compact the
    centroid landed on freshly levelled drivable ground and the nearest stand became the loader's own
    cell, a separation of exactly zero. A better footprint uncovered it rather than causing it.
    """
    t, _area, model = _stocked()
    face = _face(depth_m=10.0)
    exit_xy = _exit_of(t)
    served = 0
    for _ in range(6):
        c = next_cut(t, model, face, 1500.0, repose_deg=REPOSE)
        if c is None:
            break
        haul_cycle(t, c.cells, exit_xy=exit_xy, max_grade=MAX_GRADE).apply_to(c)
        if c.stand is None:
            continue
        served += 1
        cell = t.cell_at(*c.stand)
        assert cell not in set(c.cells), (
            f"the truck parked on cell {cell}, which is one of the {len(c.cells)} the loader dug"
        )
        assert c.loader is not None
        assert math.dist(c.stand, c.loader) > 0.0, "the truck and the loader are at the same point"
    assert served > 0, "no cut was served, so the assertion proved nothing"
