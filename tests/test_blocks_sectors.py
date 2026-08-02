"""Units 7 and 8: the raw ledger and the sector rollup.

The gate for unit 8 is that the comparison reproduces the behaviour of Minerals 2021 table 3: over
every region, the model's confidence interval on the mean is narrower than the raw observations'.
"""
from __future__ import annotations

import pytest

from bedblend.blocks import BlockModel, transfer_distances
from bedblend.design import rectangular_yard
from bedblend.dozer import level
from bedblend.dump import place_paddock
from bedblend.relax import relax_to
from bedblend.sectors import (
    CONFIDENCE_LEVELS,
    compare,
    homogeneity_map,
    quadrants,
    rollup,
    rollup_by_lift,
)
from bedblend.terrain import Terrain, TruckSpec

REPOSE = 37.0
CELL = 2.5


def _build(n_loads: int = 160, with_dozer: bool = False):
    """A small paddock base layer, recorded in the ledger as it is placed.

    Grades vary along the build so consecutive loads are correlated, which is what a dig sequence
    produces: consecutive trucks come from the same block.
    """
    t = Terrain.flat(60, 60, CELL)
    plan = rectangular_yard(
        n_areas=1, area_width_m=60.0, area_length_m=60.0, bench_height_m=6.0, n_benches=1
    )
    plan.row_spacing_m = 8.0
    area = plan.areas[0]
    truck = TruckSpec()
    model = BlockModel.over(t)
    observations: list[tuple[float, float, float]] = []

    tips = plan.paddock_tips(area, area.benches[0])[:n_loads]
    for k, tp in enumerate(tips):
        # Twenty loads per dig block, so grade is piecewise constant with a little variation inside.
        block = k // 20
        grade = 0.30 + 0.05 * block + 0.01 * ((k % 7) - 3)
        pl = place_paddock(t, tp.x_m, tp.y_m, tp.heading_rad, truck.load_volume_m3, truck)
        model.record(
            t, pl.cells, pl.added_m,
            grade=grade, source_block=block, event_id=k, lift=0, area=area.name,
            grade_uncertainty=0.12,
        )
        observations.append((tp.x_m, tp.y_m, grade))

    if with_dozer:
        for _ in range(10):
            p = level(t, area, blade_m3=60.0)
            if not p.transfers:
                break
            model.apply_transfers(p.transfers, distances=transfer_distances(t, p.transfers))

    return t, area, model, observations


# -- the ledger ------------------------------------------------------------------------------


def test_ledger_agrees_with_the_terrain():
    """The invariant that makes every downstream grade trustworthy."""
    t, _area, model, _obs = _build()
    model.assert_consistent(t)


def test_ledger_agrees_with_the_terrain_after_dozing():
    """Moving material must move its record with it, or provenance silently detaches from reality."""
    t, _area, model, _obs = _build(with_dozer=True)
    model.assert_consistent(t)


def test_relaxation_transfers_can_be_applied_to_the_ledger():
    t = Terrain.flat(40, 40, CELL)
    truck = TruckSpec()
    model = BlockModel.over(t)
    pl = place_paddock(t, 50.0, 50.0, 0.0, truck.load_volume_m3, truck)
    model.record(t, pl.cells, pl.added_m, grade=0.4, source_block=1, event_id=0, lift=0, area="A1")
    moves = relax_to(t, REPOSE)
    model.apply_transfers(
        [(a, b, v * model.cell_area_m2) for a, b, v in moves],
        distances=transfer_distances(t, [(a, b, v) for a, b, v in moves]),
    )
    model.assert_consistent(t)


def test_tonnage_matches_the_material_placed():
    _t, _area, model, _obs = _build(n_loads=40)
    truck = TruckSpec()
    expected = 40 * truck.load_volume_m3 * model.bulk_density_t_m3
    assert model.total_tonnes() == pytest.approx(expected, rel=1e-6)


def test_dozing_accumulates_displacement_so_provenance_is_not_overclaimed():
    """v1 reported provenance to 1e-12. With a dozer in the model that precision is fiction."""
    _t, _area, undozed, _o = _build()
    _t2, _a2, dozed, _o2 = _build(with_dozer=True)
    assert undozed.mean_displacement_m() == 0.0
    assert dozed.mean_displacement_m() > 0.0


def test_block_export_preserves_tonnage():
    """The regular block model is a VIEW; it must not invent or lose material."""
    _t, _area, model, _obs = _build(n_loads=80)
    blocks = model.to_blocks(dz_m=5.0)
    assert blocks
    assert sum(tn for *_r, tn in blocks) == pytest.approx(model.total_tonnes(), rel=1e-6)


# -- sectors ---------------------------------------------------------------------------------


def test_sector_rollup_is_tonnage_weighted():
    t, area, model, _obs = _build()
    r = rollup(model, t, area)
    assert r.n > 0
    # A sector holds what landed inside it, which is not everything placed: loads tipped near the
    # boundary spread across it. Most of the material is inside, and none of it is invented.
    total = model.total_tonnes()
    assert 0.85 * total < r.tonnes < total
    assert 0.25 < r.mean_grade < 0.70
    for lv in CONFIDENCE_LEVELS:
        assert r.ci[lv] > 0
    # Wider confidence means a wider interval, in the right order.
    assert r.ci[0.90] < r.ci[0.95] < r.ci[0.99]


def test_lift_rollup_exposes_what_the_whole_sector_average_hides():
    t, area, model, _obs = _build()
    whole = rollup(model, t, area)
    lift0 = rollup_by_lift(model, t, area, 0)
    # Only one lift here, so they must agree; the point of the test is that the restriction works
    # rather than silently returning nothing.
    assert lift0.n > 0
    assert lift0.mean_grade == pytest.approx(whole.mean_grade, rel=1e-9)


def test_quadrants_partition_the_area():
    _t, area, _m, _o = _build()
    qs = quadrants(area)
    assert len(qs) == 4
    assert sum(q.plan_area_m2 for q in qs) == pytest.approx(area.plan_area_m2)
    assert [q.name.split()[-2:] for q in qs] == [
        ["bottom", "left"], ["bottom", "right"], ["top", "left"], ["top", "right"]
    ]


def test_model_interval_is_tighter_than_the_data_in_every_quadrant():
    """THE UNIT GATE, reproducing Minerals 2021 table 3.

    "for each quadrant and confidence level, the model has a smaller confidence interval value than
    that of the example data". The model is smoother because every column mixes several loads, which
    is a genuine property and also the reason a sector rollup can look reassuring while the raw field
    under it is not.
    """
    t, area, model, obs = _build()
    for q in quadrants(area):
        cmp_ = compare(model, t, q, obs)
        if cmp_.data.n < 3 or cmp_.model.n < 3:
            continue
        for lv in CONFIDENCE_LEVELS:
            assert cmp_.model.ci[lv] < cmp_.data.ci[lv], (
                f"{q.name} at {lv:.0%}: model {cmp_.model.ci[lv]:.6f} "
                f"is not tighter than data {cmp_.data.ci[lv]:.6f}"
            )


def test_homogeneity_map_finds_the_uniform_ground():
    """Low dispersion where the material came from one dig block, higher where blocks meet."""
    t, _area, model, _obs = _build()
    h = homogeneity_map(model, t, window=3)
    vals = [v for v in h if v is not None]
    assert vals, "the homogeneity map is empty"
    assert min(vals) < max(vals), "the map is flat, so it distinguishes nothing"
