"""Units 1 to 3 and 5: terrain, relaxation, and the two dump operators.

The important test in this file is ``test_edge_dump_matches_measured_envelope``. It is the kill
criterion the plan states: if the edge operator cannot produce dumps inside the envelope measured
across 28 real dumps, the operator is wrong and gets redesigned rather than tuned.
"""
from __future__ import annotations

import math

import pytest

from bedblend.design import Phase, rectangular_yard
from bedblend.dump import (
    MEASURED_LENGTH_M,
    MEASURED_THICKNESS_M,
    MEASURED_WIDTH_M,
    DumpProfile,
    classify,
    distance_to_crest,
    place_edge,
    place_paddock,
    run_out_for_bench,
)
from bedblend.relax import ReposeViolation, assert_stable, count_over_repose, relax_to, settle
from bedblend.terrain import Terrain, TruckSpec

REPOSE = 37.0
CELL = 2.5


def pad(nx: int = 80, ny: int = 80) -> Terrain:
    return Terrain.flat(nx, ny, CELL)


# -- terrain ---------------------------------------------------------------------------------


def test_empty_pad_has_no_material_and_no_crest():
    t = pad()
    assert t.volume_m3() == pytest.approx(0.0)
    assert not any(t.has_material(c) for c in range(t.n_cells))
    # No face on an empty pad, which is why the first campaign has to be paddock dumping.
    assert t.crest_cells(min_drop_m=0.5) == []
    assert distance_to_crest(t, 50.0, 50.0, []) == float("inf")


def test_outward_normal_points_downhill():
    t = pad(40, 40)
    # A ramp rising in +x. Steepest descent is therefore -x.
    for c in range(t.n_cells):
        i, _ = t.ij(c)
        t.z[c] = i * 0.5
    nx_, ny_ = t.outward_normal(t.idx(20, 20))
    assert nx_ == pytest.approx(-1.0, abs=1e-9)
    assert ny_ == pytest.approx(0.0, abs=1e-9)


def test_trafficability_refuses_a_steep_cell():
    t = pad(20, 20)
    t.z[t.idx(10, 10)] = 10.0
    max_grade = math.tan(math.radians(REPOSE)) / 1.5
    assert not t.trafficable(t.idx(10, 10), max_grade)
    assert t.trafficable(t.idx(2, 2), max_grade)


# -- relaxation ------------------------------------------------------------------------------


def test_relaxation_conserves_mass_and_leaves_zero_violations():
    t = pad()
    c = t.idx(40, 40)
    t.z[c] = 60.0
    before = t.volume_m3()

    relax_to(t, REPOSE, active={c})

    assert t.volume_m3() == pytest.approx(before, rel=1e-12)
    n_over, worst = count_over_repose(t.z, t.nx, t.ny, t.cell_m, REPOSE)
    # The defect this replaces left 446 pairs standing, the worst at 55.9 degrees against 37.
    assert n_over == 0
    assert worst <= REPOSE + 1e-6


def test_assert_stable_raises_on_an_unrelaxed_field():
    t = pad(20, 20)
    t.z[t.idx(10, 10)] = 40.0
    with pytest.raises(ReposeViolation) as e:
        assert_stable(t, REPOSE)
    # The message has to carry the numbers, because that is what distinguishes a solver failure from
    # a caller that passed the wrong angle.
    msg = str(e.value)
    assert "pairs stand more than" in msg and "deg" in msg


def test_the_stability_tolerance_is_a_degree_and_not_a_micrometre():
    """A pair a hair over the angle is not a defect; one nineteen degrees over is.

    The angle of repose is known to a few degrees at best, so asserting a surface to floating-point
    equality against it fails builds over residue no solver can shift while catching nothing a
    coarser check would miss.
    """
    from bedblend.relax import STABLE_TOL_DEG

    t = pad(20, 20)
    c = t.idx(10, 10)
    # A slope just inside the tolerance over repose: not a violation.
    run = t.cell_m
    t.z[c] = run * math.tan(math.radians(REPOSE + STABLE_TOL_DEG * 0.5))
    assert_stable(t, REPOSE)

    # And just outside it: a violation.
    t.z[c] = run * math.tan(math.radians(REPOSE + STABLE_TOL_DEG * 2.0))
    with pytest.raises(ReposeViolation):
        assert_stable(t, REPOSE)


def test_settle_relaxes_through_the_fresh_slope_to_repose():
    t = pad()
    c = t.idx(40, 40)
    t.z[c] = 40.0
    before = t.volume_m3()
    settle(t, REPOSE, active={c})
    assert t.volume_m3() == pytest.approx(before, rel=1e-12)
    assert_stable(t, REPOSE)


def test_relaxation_after_removal_also_holds():
    """Reclaim must relax too.

    In the previous engine the cascade ran only on deposition and never after a cut, so a reclaim could
    leave a vertical face standing forever. This asserts the other half of the invariant.
    """
    t = pad()
    c = t.idx(40, 40)
    t.z[c] = 50.0
    relax_to(t, REPOSE, active={c})
    # Cut a hole, as a loader would.
    for cc in [t.idx(i, j) for i in range(36, 45) for j in range(36, 45)]:
        t.z[cc] = max(t.z[cc] - 8.0, 0.0)
    relax_to(t, REPOSE)
    assert_stable(t, REPOSE)


# -- paddock dumps ---------------------------------------------------------------------------


def test_paddock_dump_conserves_volume_and_is_truck_sized():
    t = pad()
    truck = TruckSpec()
    v = truck.load_volume_m3
    p = place_paddock(t, 100.0, 100.0, 0.0, v, truck)

    assert t.volume_m3() == pytest.approx(v, rel=1e-9)
    assert sum(p.added_m) * t.cell_m ** 2 == pytest.approx(v, rel=1e-9)
    assert p.profile is DumpProfile.PADDOCK
    # Sized by the machine: about a body length along the heading, about a bed width across it,
    # to within the pad's own discretisation.
    assert p.length_m == pytest.approx(truck.body_length_m, abs=2 * CELL)
    assert p.width_m == pytest.approx(truck.bed_width_m, abs=2 * CELL)


def test_paddock_heading_rotates_the_footprint():
    truck = TruckSpec()
    v = truck.load_volume_m3
    a = place_paddock(pad(), 100.0, 100.0, 0.0, v, truck)
    b = place_paddock(pad(), 100.0, 100.0, math.pi / 2, v, truck)
    # The long axis follows the heading, so the two placements are transposes of one another.
    assert a.length_m == pytest.approx(b.length_m, abs=CELL)
    assert a.width_m == pytest.approx(b.width_m, abs=CELL)
    assert a.length_m > a.width_m


# -- edge dumps, the calibration gate ---------------------------------------------------------


def _face(nx: int = 120, ny: int = 120, bench_h: float = 20.0, angle: float = 34.0) -> Terrain:
    """A flat-topped bench with a face falling away in +x, which is what an edge dump needs."""
    t = Terrain.flat(nx, ny, CELL)
    run = run_out_for_bench(bench_h, angle)
    crest_x = 60.0
    for c in range(t.n_cells):
        x, _ = t.xy(c)
        if x <= crest_x:
            t.z[c] = bench_h
        elif x < crest_x + run:
            t.z[c] = bench_h * (1.0 - (x - crest_x) / run)
        else:
            t.z[c] = 0.0
    return t


def test_edge_dump_runs_perpendicular_to_the_crest_tangent():
    t = _face()
    truck = TruckSpec()
    p = place_edge(
        t, 59.0, 150.0, truck.load_volume_m3, truck,
        profile=DumpProfile.OVAL, run_out_m=run_out_for_bench(20.0, 34.0),
    )
    # The face falls in +x, so the streak must run in +x, not along the crest.
    assert math.cos(p.heading_rad) == pytest.approx(1.0, abs=1e-6)
    assert p.length_m > p.width_m


def test_edge_dump_on_flat_ground_falls_back_to_a_heap():
    """No face means no cascade. Manufacturing a streak where the terrain cannot send material would
    be inventing the very geometry this module exists to stop inventing."""
    t = pad()
    truck = TruckSpec()
    p = place_edge(
        t, 100.0, 100.0, truck.load_volume_m3, truck,
        profile=DumpProfile.COMET, run_out_m=30.0,
    )
    assert p.profile is DumpProfile.PADDOCK


@pytest.mark.parametrize(
    "profile",
    [DumpProfile.OVAL, DumpProfile.COMET, DumpProfile.RECTANGULAR, DumpProfile.SLOUGHED_HEAP],
)
def test_edge_dump_matches_measured_envelope(profile: DumpProfile):
    """THE KILL CRITERION.

    Every profile, placed on a realistic bench, must land inside the envelope measured across the 28
    UAV-surveyed dumps of Mining 2022 table 5: length 13 to 46 m, width 11 to 23 m, maximum thickness
    0.368 to 2.032 m. The previous engine's 4.5 m isotropic disc fails all three.
    """
    bench_h, angle = 20.0, 34.0
    t = _face(bench_h=bench_h, angle=angle)
    truck = TruckSpec()
    p = place_edge(
        t, 59.0, 150.0, truck.load_volume_m3, truck,
        profile=profile, run_out_m=run_out_for_bench(bench_h, angle),
    )

    assert t.volume_m3() > 0
    assert MEASURED_LENGTH_M[0] <= p.length_m <= MEASURED_LENGTH_M[1], (
        f"{profile.value}: length {p.length_m:.1f} m outside the measured {MEASURED_LENGTH_M}"
    )
    assert MEASURED_WIDTH_M[0] <= p.width_m <= MEASURED_WIDTH_M[1], (
        f"{profile.value}: width {p.width_m:.1f} m outside the measured {MEASURED_WIDTH_M}"
    )
    assert MEASURED_THICKNESS_M[0] <= p.max_thickness_m <= MEASURED_THICKNESS_M[1], (
        f"{profile.value}: thickness {p.max_thickness_m:.2f} m outside {MEASURED_THICKNESS_M}"
    )


def test_edge_dump_biases_mass_toward_the_toe():
    """"aggregates more at the bottom of the dumping area ... and less near the top crest"."""
    t = _face()
    truck = TruckSpec()
    run = run_out_for_bench(20.0, 34.0)
    p = place_edge(
        t, 59.0, 150.0, truck.load_volume_m3, truck,
        profile=DumpProfile.OVAL, run_out_m=run,
    )
    upper = lower = 0.0
    for c, dz in zip(p.cells, p.added_m):
        x, _ = t.xy(c)
        if x - 59.0 > run / 2:
            lower += dz
        else:
            upper += dz
    assert lower > upper


# -- profile selection -----------------------------------------------------------------------


def test_far_from_the_crest_gives_a_sloughed_heap():
    """"if the truck dumps far from the crest of the dump face, it will create a sloughed heap"."""
    truck = TruckSpec()
    assert classify(3.0 * truck.body_length_m, truck) is DumpProfile.SLOUGHED_HEAP


def test_against_the_crest_gives_one_of_the_other_three():
    """"When the truck dumps against the crest ... either comet, oval or rectangular"."""
    truck = TruckSpec()
    seen = {classify(0.5, truck, rand=r / 50.0) for r in range(50)}
    assert DumpProfile.SLOUGHED_HEAP not in seen
    assert seen <= {DumpProfile.OVAL, DumpProfile.COMET, DumpProfile.RECTANGULAR}
    # All three occur, in their measured proportions.
    assert len(seen) == 3


# -- the plan --------------------------------------------------------------------------------


def test_yard_plan_generates_ordered_tips_inside_its_areas():
    plan = rectangular_yard(
        n_areas=2, area_width_m=57.0, area_length_m=150.0,
        bench_height_m=8.7, n_benches=2, classes=["high", "low"],
    )
    truck = TruckSpec()
    tips = plan.program(load_volume_m3=truck.load_volume_m3, run_out_m=15.0)

    assert tips, "the plan produced no tip positions"
    # Every tip lies inside the area it names, which is what makes the areas real constraints.
    for tp in tips:
        assert plan.area(tp.area).contains(tp.x_m, tp.y_m)
    # Both phases are present, and the base layer is laid before the upper layer.
    first_edge = next(k for k, tp in enumerate(tips) if tp.phase is Phase.EDGE)
    assert all(tp.phase is Phase.PADDOCK for tp in tips[:first_edge])


def test_paddock_lattice_never_stacks_two_loads_on_one_spot():
    """A stockpile cannot be fed repeatedly at one point, so the lattice must not ask it to."""
    plan = rectangular_yard(
        n_areas=1, area_width_m=57.0, area_length_m=150.0,
        bench_height_m=8.7, n_benches=1,
    )
    area = plan.areas[0]
    tips = plan.paddock_tips(area, area.benches[0])
    positions = {(round(tp.x_m, 6), round(tp.y_m, 6)) for tp in tips}
    assert len(positions) == len(tips)
