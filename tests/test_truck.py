"""Unit 6: trucks with routes, spotting and departures.

The gate the plan sets is that paths are drawn on approach and departure. Behind that is the harder
requirement: access must be a real constraint, so a tip the pile has grown over must be refused rather
than silently served.
"""
from __future__ import annotations

import math

import pytest

from bedblend.design import Phase, TipPosition
from bedblend.dump import place_edge, place_paddock, run_out_for_bench
from bedblend.relax import relax_to
from bedblend.terrain import Terrain, TruckSpec
from bedblend.truck import CycleState, Fleet, NoRoute, Payload, Route, solve_route, spot

REPOSE = 37.0
CELL = 2.5
MAX_GRADE = math.tan(math.radians(REPOSE)) / 1.5


def tip(x: float, y: float, heading: float = 0.0, phase: Phase = Phase.PADDOCK) -> TipPosition:
    return TipPosition(x, y, heading, phase, "A1", 0, 0)


def _bench(nx: int = 100, ny: int = 100, bh: float = 20.0, ang: float = 34.0) -> Terrain:
    """A flat bench top with a face falling away in +x."""
    t = Terrain.flat(nx, ny, CELL)
    run = run_out_for_bench(bh, ang)
    crest_x = 100.0
    for c in range(t.n_cells):
        x, _ = t.xy(c)
        t.z[c] = bh if x <= crest_x else (bh * (1.0 - (x - crest_x) / run) if x < crest_x + run else 0.0)
    return t


# -- routing ---------------------------------------------------------------------------------


def test_route_across_an_empty_pad_is_essentially_straight():
    t = Terrain.flat(60, 60, CELL)
    r = solve_route(t, (10.0, 10.0), (130.0, 130.0), max_grade=MAX_GRADE)
    straight = math.dist((10.0, 10.0), (130.0, 130.0))
    # A* on true distance, so the path should be within a few percent of the straight line, not the
    # 41 percent longer a step-count cost would give on a diagonal.
    assert r.length_m == pytest.approx(straight, rel=0.05)
    # And it is stored as a polyline, not one point per cell.
    assert len(r.points) < 10


def test_a_route_refuses_ground_the_truck_cannot_climb():
    """Access is a constraint. A tip walled off by steep ground has no route to it."""
    t = Terrain.flat(60, 60, CELL)
    # A wall across the middle, with material either side of it left flat.
    for c in range(t.n_cells):
        x, _ = t.xy(c)
        if 70.0 <= x <= 80.0:
            t.z[c] = 30.0
    with pytest.raises(NoRoute):
        solve_route(t, (10.0, 75.0), (140.0, 75.0), max_grade=MAX_GRADE)


def test_a_route_goes_around_an_obstacle_rather_than_over_it():
    t = Terrain.flat(60, 60, CELL)
    for c in range(t.n_cells):
        x, y = t.xy(c)
        if 70.0 <= x <= 80.0 and y <= 100.0:      # a wall with a gap at the top
            t.z[c] = 30.0
    r = solve_route(t, (10.0, 50.0), (140.0, 50.0), max_grade=MAX_GRADE)
    straight = math.dist((10.0, 50.0), (140.0, 50.0))
    assert r.length_m > straight          # it had to detour
    # And it actually went round the end of the wall.
    assert max(p[1] for p in r.points) > 100.0


def test_route_interpolation_walks_the_whole_path():
    t = Terrain.flat(40, 40, CELL)
    r = solve_route(t, (10.0, 10.0), (80.0, 80.0), max_grade=MAX_GRADE)
    assert r.position_at(0.0) == pytest.approx(r.points[0])
    assert r.position_at(1.0) == pytest.approx(r.points[-1])
    mid = r.position_at(0.5)
    assert math.dist(r.points[0], mid) > 0
    assert math.dist(mid, r.points[-1]) > 0


# -- spotting --------------------------------------------------------------------------------


def test_spotting_discharges_behind_the_truck_when_there_is_no_face():
    """A rear-dump truck reverses in, so the load leaves opposite the way it drove."""
    t = Terrain.flat(40, 40, CELL)
    approach = Route([(10.0, 50.0), (50.0, 50.0)])     # driving in +x
    heading, d = spot(t, approach, tip(50.0, 50.0), crest=[])
    assert math.cos(heading) == pytest.approx(-1.0, abs=1e-9)
    assert d == float("inf")


def test_spotting_at_a_crest_takes_its_heading_from_the_face():
    """"runs perpendicular to the tangent of the dump location": the terrain wins over the plan,
    because the plan was written before the face moved."""
    t = _bench()
    crest = t.crest_cells(min_drop_m=0.5)
    assert crest, "the fixture has no crest"
    # Drive in along -y, which is NOT the direction of the face.
    approach = Route([(99.0, 150.0), (99.0, 120.0)])
    heading, d = spot(t, approach, tip(99.0, 120.0), crest=crest)
    # The face falls in +x, so the discharge must run in +x regardless of how the truck arrived.
    assert math.cos(heading) == pytest.approx(1.0, abs=1e-6)
    assert d < 3.0 * (4.0 * CELL)


# -- the cycle -------------------------------------------------------------------------------


def test_dispatch_records_an_approach_and_depart_records_a_departure():
    """The gate: the path exists before the dump and after it, so both can be drawn."""
    t = Terrain.flat(80, 80, CELL)
    fleet = Fleet.of(3, TruckSpec(), (10.0, 10.0), repose_deg=REPOSE)
    truck = fleet.trucks[0]
    payload = Payload(tonnes=231.0, grade=0.42, source_block=7, grade_uncertainty=0.12)

    heading, _d = fleet.dispatch(t, truck, tip(120.0, 120.0), payload)
    assert truck.state is CycleState.DUMPING
    assert truck.payload is payload
    assert len(truck.approach.points) >= 2
    assert truck.approach.length_m > 0
    assert (truck.x_m, truck.y_m) == (120.0, 120.0)

    # The load lands BEHIND the truck, not under it.
    dx, dy = truck.discharge_xy()
    place_paddock(t, dx, dy, heading, truck.spec.load_volume_m3, truck.spec)
    relax_to(t, REPOSE)

    dep = fleet.depart(t, truck, exit_xy=(190.0, 10.0))
    assert truck.state is CycleState.QUEUED_AT_SHOVEL
    assert truck.payload is None
    assert len(dep.points) >= 2
    assert dep.length_m > 0
    # It left by a different way than it came, which is what a tip head cycle does.
    assert dep.points[-1] != truck.approach.points[0]


def test_an_unreachable_tip_is_refused_not_served():
    """The pile constrains its own construction.

    A tip sitting on top of a fresh, steep heap has no drivable route, and the model must say so. This
    is the mechanism that makes it impossible to feed a stockpile repeatedly at one point.
    """
    t = Terrain.flat(60, 60, CELL)
    # A tall cone with no relaxation: nothing on its flank is drivable.
    t.z[t.idx(30, 30)] = 40.0
    for c in t.neighbours(t.idx(30, 30)):
        t.z[c] = 30.0
    fleet = Fleet.of(1, TruckSpec(), (10.0, 10.0), repose_deg=REPOSE)
    with pytest.raises(NoRoute):
        fleet.dispatch(t, fleet.trucks[0], tip(76.25, 76.25), Payload(231.0, 0.4, 1))


def test_repeated_dumping_at_one_point_becomes_unreachable():
    """The physical impossibility, demonstrated rather than asserted.

    Load after load at the same coordinate raises the ground until no route reaches it. The engine is
    not told this; it falls out of trafficability.
    """
    t = Terrain.flat(60, 60, CELL)
    fleet = Fleet.of(1, TruckSpec(), (5.0, 5.0), repose_deg=REPOSE)
    truck = fleet.trucks[0]
    spot_xy = (75.0, 75.0)

    placed = 0
    for _ in range(60):
        try:
            heading, _ = fleet.dispatch(t, truck, tip(*spot_xy), Payload(231.0, 0.4, 1))
        except NoRoute:
            break
        # No relaxation between loads: this is one truck tipping on one spot, which is exactly the
        # case that cannot physically continue.
        dx, dy = truck.discharge_xy()
        place_paddock(t, dx, dy, heading, truck.spec.load_volume_m3, truck.spec)
        placed += 1

    assert placed > 0, "the very first load should have been placeable on an empty pad"
    assert placed < 60, "the pile never became unreachable, so access is not constraining anything"


def test_the_fleet_derives_its_gradient_limit_from_the_repose_angle():
    fleet = Fleet.of(1, TruckSpec(), (0.0, 0.0), repose_deg=37.0, grade_limit_divisor=1.5)
    assert fleet.max_grade == pytest.approx(math.tan(math.radians(37.0)) / 1.5)


def test_edge_dump_uses_the_spotted_heading():
    """End to end: route in, spot against the face, cascade down it."""
    t = _bench()
    crest = t.crest_cells(min_drop_m=0.5)
    fleet = Fleet.of(1, TruckSpec(), (10.0, 120.0), repose_deg=REPOSE)
    truck = fleet.trucks[0]
    tp = tip(97.5, 120.0, phase=Phase.EDGE)

    heading, d_crest = fleet.dispatch(t, truck, tp, Payload(231.0, 0.4, 3), crest=crest)
    assert d_crest < 20.0

    from bedblend.dump import DumpProfile

    pl = place_edge(
        t, tp.x_m, tp.y_m, truck.spec.load_volume_m3, truck.spec,
        profile=DumpProfile.OVAL,
        run_out_m=run_out_for_bench(20.0, 34.0),
        normal=(math.cos(heading), math.sin(heading)),
        distance_to_crest_m=d_crest,
    )
    assert pl.length_m > pl.width_m
    assert math.cos(pl.heading_rad) == pytest.approx(1.0, abs=1e-6)
