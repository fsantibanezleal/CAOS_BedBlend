"""Unit 4: the dozer.

The gate the plan sets for this unit is that a bench floor is produced and is drivable. A paddock
campaign leaves a lattice of separate heaps that no truck can cross; if the dozer cannot turn that
into a working level, nothing in the model ever completes a lift.
"""
from __future__ import annotations

import math

import pytest

from bedblend.design import rectangular_yard
from bedblend.dozer import build_berm, level, push_to_crest
from bedblend.dump import place_paddock
from bedblend.relax import assert_stable, relax_to
from bedblend.terrain import Terrain, TruckSpec

REPOSE = 37.0
CELL = 2.5


def _paddock_field() -> tuple[Terrain, object]:
    """A small area with a complete paddock base layer laid down on it, unlevelled.

    Rows are close enough to actually cover the area. That matters for what is being tested: with
    widely separated rows the bare ground between them sits further from the ridges than a dozer can
    push in one pass, so the dozer correctly declines to fill it and the area never levels. That is
    real behaviour, not a defect, but it is not a base layer, and levelling a base layer is what this
    unit's gate is about.
    """
    t = Terrain.flat(60, 60, CELL)
    plan = rectangular_yard(
        n_areas=1, area_width_m=60.0, area_length_m=60.0,
        bench_height_m=6.0, n_benches=1,
    )
    plan.row_spacing_m = 8.0
    area = plan.areas[0]
    truck = TruckSpec()
    for tp in plan.paddock_tips(area, area.benches[0]):
        place_paddock(t, tp.x_m, tp.y_m, tp.heading_rad, truck.load_volume_m3, truck)
    relax_to(t, REPOSE)
    return t, area


def test_levelling_conserves_mass():
    t, area = _paddock_field()
    before = t.volume_m3()
    level(t, area)
    assert t.volume_m3() == pytest.approx(before, rel=1e-9)


def test_levelling_flattens_the_working_floor():
    """The gate: heaps become a floor.

    Measured as the spread of elevations over the area. A lattice of frustums has a large spread; a
    dozed floor has a small one.
    """
    t, area = _paddock_field()
    cells = [c for c in range(t.n_cells) if area.contains(*t.xy(c))]

    def spread() -> float:
        zs = [t.z[c] for c in cells]
        return max(zs) - min(zs)

    before = spread()
    # A real dozer makes several passes; one pass is bounded by the blade.
    for _ in range(40):
        if not level(t, area, blade_m3=60.0).transfers:
            break
    after = spread()
    assert after < before / 2.0, f"levelling barely helped: {before:.2f} m -> {after:.2f} m"


def test_levelled_floor_is_drivable():
    """A floor nobody can drive on has not been levelled, whatever its elevation spread says."""
    t, area = _paddock_field()
    for _ in range(60):
        if not level(t, area, blade_m3=60.0).transfers:
            break
    relax_to(t, REPOSE)

    max_grade = math.tan(math.radians(REPOSE)) / 1.5
    # The window is derived from the area, not written as literals. It used to be 10 to 50 metres,
    # which was inside the area only while areas started at the pad origin; once they were offset by
    # a margin the window sampled mostly bare pad and the assertion measured nothing.
    core = area.inset(10.0)
    inner = [c for c in range(t.n_cells) if core.contains(*t.xy(c))]
    drivable = sum(1 for c in inner if t.trafficable(c, max_grade))
    assert drivable / len(inner) > 0.9, (
        f"only {drivable}/{len(inner)} of the levelled floor is trafficable"
    )


def test_dozer_reports_displacement_so_provenance_can_be_honest():
    """The dozer mixes material "in intractable ways", so it must say how far it moved things.

    A pass that moved material but reported zero displacement would let the ledger keep claiming a
    precision the operation does not have.
    """
    t, area = _paddock_field()
    p = level(t, area, blade_m3=60.0)
    assert p.volume_moved_m3 > 0
    assert p.mean_displacement_m > 0
    assert p.max_displacement_m >= p.mean_displacement_m
    # Every transfer is accounted for in the volume total.
    assert sum(v for _, _, v in p.transfers) == pytest.approx(p.volume_moved_m3, rel=1e-9)


def test_dozer_respects_its_push_limit():
    t, area = _paddock_field()
    p = level(t, area, push_m=10.0, blade_m3=60.0)
    assert p.max_displacement_m <= 10.0 + 1e-9


def test_push_to_crest_conserves_mass_and_moves_material_along_the_normal():
    t, area = _paddock_field()
    for _ in range(40):
        if not level(t, area, blade_m3=60.0).transfers:
            break
    before = t.volume_m3()
    p = push_to_crest(t, area, normal=(1.0, 0.0), depth_m=0.2, push_m=10.0)
    assert t.volume_m3() == pytest.approx(before, rel=1e-9)
    # Everything moved in +x, which is the direction of the face.
    for a, b, _ in p.transfers:
        assert t.xy(b)[0] > t.xy(a)[0]


def test_berm_costs_material_rather_than_appearing_from_nowhere():
    t, area = _paddock_field()
    for _ in range(40):
        if not level(t, area, blade_m3=60.0).transfers:
            break
    crest = t.crest_cells(min_drop_m=0.3)
    before = t.volume_m3()
    build_berm(t, crest, height_m=0.5, source_depth_m=0.1)
    assert t.volume_m3() == pytest.approx(before, rel=1e-9)


def test_a_levelled_and_relaxed_floor_holds_the_repose_angle():
    """Every operation that moves material must leave a relaxable surface. In the previous engine the
    cascade ran only on deposition, so an operation like this one could leave a face standing."""
    t, area = _paddock_field()
    for _ in range(40):
        if not level(t, area, blade_m3=60.0).transfers:
            break
    push_to_crest(t, area, normal=(1.0, 0.0), depth_m=0.2, push_m=10.0)
    relax_to(t, REPOSE)
    assert_stable(t, REPOSE)
