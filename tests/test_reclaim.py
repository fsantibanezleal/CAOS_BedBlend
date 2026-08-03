"""Unit 9: sequenced reclaim from a real face.

Two things the previous engine got wrong are asserted here directly: a cut must relax what it
undercuts, and the machine must engage a face rather than an integer position.
"""
from __future__ import annotations

import pytest

from bedblend.blocks import BlockModel, transfer_distances
from bedblend.design import rectangular_yard
from bedblend.dump import place_paddock
from bedblend.reclaim import Cut, ReclaimFace, ReclaimMethod, advance, campaign, cut
from bedblend.relax import assert_stable, relax_to
from bedblend.terrain import Terrain, TruckSpec

REPOSE = 37.0
CELL = 2.5


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
    """The extraction order is a real decision. If it does not change the feed, it is not modelled."""
    t1, _a1, m1 = _stocked()
    t2, _a2, m2 = _stocked()
    c_lifo = cut(t1, m1, _face(method=ReclaimMethod.LIFO), 3000.0, repose_deg=REPOSE)
    c_fifo = cut(t2, m2, _face(method=ReclaimMethod.FIFO), 3000.0, repose_deg=REPOSE)
    assert c_lifo.tonnes == pytest.approx(c_fifo.tonnes, rel=1e-6)
    assert c_lifo.grade != pytest.approx(c_fifo.grade, rel=1e-6)


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
    a top-down cut does not. The blending method must show lower feed variance."""
    def feed(method: ReclaimMethod) -> list[float]:
        t, _a, m = _stocked()
        cs = campaign(
            t, m, _face(method=method, depth_m=10.0),
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
