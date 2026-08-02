"""Ground that is not flat, and building on it.

Only one of the five published fill types is a flat pad. The gate for this unit is that a stockpile
can be built on real relief and still hold every invariant, and that the topography actually
constrains where equipment can go rather than being decoration.
"""
from __future__ import annotations

import math

import pytest

from bedblend.build import build
from bedblend.design import rectangular_yard
from bedblend.relax import assert_stable
from bedblend.stream import dig_sequence, payloads_from
from bedblend.terrain import TruckSpec
from bedblend.topography import FillType, buildable_fraction, ground, relief_stats
from bedblend.truck import Fleet

REPOSE = 37.0
CELL = 2.5
MAX_GRADE = math.tan(math.radians(REPOSE)) / 1.5


@pytest.mark.parametrize("fill", list(FillType))
def test_every_fill_type_produces_ground_and_keeps_z0(fill: FillType):
    t = ground(fill, 48, 48, CELL, relief_m=25.0)
    assert t.z == t.z0, "fresh ground must have no material on it"
    assert t.volume_m3() == pytest.approx(0.0), "fresh ground must contain no stockpiled material"
    assert not any(t.has_material(c) for c in range(t.n_cells))


def test_heaped_fill_is_the_flat_one_and_the_others_are_not():
    """The taxonomy's point: only heaped fill is a flat pad."""
    flat = relief_stats(ground(FillType.HEAPED, 48, 48, CELL, relief_m=25.0))
    assert flat["relief_m"] == pytest.approx(0.0)
    for fill in (FillType.SIDEHILL, FillType.VALLEY, FillType.CROSS_VALLEY, FillType.RIDGE_CREST):
        s = relief_stats(ground(fill, 48, 48, CELL, relief_m=25.0))
        assert s["relief_m"] > 10.0, f"{fill.value} came out nearly flat"


def test_valley_is_low_in_the_middle_and_a_ridge_is_high_there():
    v = ground(FillType.VALLEY, 48, 48, CELL, relief_m=30.0)
    r = ground(FillType.RIDGE_CREST, 48, 48, CELL, relief_m=30.0)
    mid = v.idx(24, 24)
    edge = v.idx(24, 1)
    assert v.z0[mid] < v.z0[edge], "a valley must be lower along its axis than at its sides"
    assert r.z0[mid] > r.z0[edge], "a ridge must be higher along its crest than at its flanks"


def test_topography_constrains_where_equipment_can_go_before_anything_is_built():
    """THE POINT OF THE MODULE. Relief is not decoration: it decides the buildable ground."""
    flat = buildable_fraction(ground(FillType.HEAPED, 48, 48, CELL), MAX_GRADE)
    steep = buildable_fraction(
        ground(FillType.SIDEHILL, 48, 48, CELL, relief_m=60.0), MAX_GRADE
    )
    assert flat == pytest.approx(1.0), "a prepared flat pad is entirely drivable"
    assert steep < flat, "a 60 m sidehill must restrict access relative to a flat pad"


def test_roughness_is_smooth_relief_not_per_cell_static():
    """White noise would make every cell locally steep and the access mask would come out as static,
    which is a modelling artefact rather than terrain."""
    t = ground(FillType.HEAPED, 48, 48, CELL, relief_m=0.0, roughness_m=1.5, seed=3)
    s = relief_stats(t)
    assert s["relief_m"] > 0.2, "roughness produced no relief at all"
    # A smooth field stays well under the equipment limit; static would not.
    assert s["max_gradient"] < MAX_GRADE, (
        f"roughness alone made the ground undrivable at {s['max_slope_deg']:.0f} deg"
    )
    assert min(t.z0) >= 0.0, "roughness pushed the ground below zero"


def test_a_stockpile_builds_on_a_sidehill_and_holds_every_invariant():
    """The gate: real relief, real build, same invariants."""
    t = ground(FillType.SIDEHILL, 56, 56, CELL, relief_m=18.0, roughness_m=0.4, seed=5)
    plan = rectangular_yard(
        n_areas=1, area_width_m=70.0, area_length_m=70.0,
        bench_height_m=8.0, n_benches=1, classes=["ROM"],
    )
    plan.row_spacing_m, plan.tip_spacing_m = 10.0, 8.0
    plan.areas[0].access_xy = (70.0, 0.0)
    fleet = Fleet.of(3, TruckSpec(), (130.0, 12.0), repose_deg=REPOSE)
    loads = payloads_from(dig_sequence(n_loads=90, seed=11), seed=11)

    res = build(t, plan, fleet, loads, repose_deg=REPOSE)

    assert res.placed, "nothing could be built on the sidehill at all"
    assert_stable(res.terrain, REPOSE)
    res.model.assert_consistent(res.terrain)
    # Material volume is measured against the ORIGINAL ground, which is the whole reason z0 is kept.
    expected = len(res.placed) * TruckSpec().load_volume_m3
    assert res.terrain.volume_m3() == pytest.approx(expected, rel=1e-6)


def test_material_volume_is_measured_against_original_ground_not_the_surface():
    """On sloping ground "how high is the surface" and "how much material is here" diverge at once,
    and code that confuses them reports a hillside as a stockpile."""
    t = ground(FillType.SIDEHILL, 32, 32, CELL, relief_m=20.0)
    assert t.volume_m3() == pytest.approx(0.0)
    assert sum(t.z) > 0.0, "the fixture has no relief, so it proves nothing"
