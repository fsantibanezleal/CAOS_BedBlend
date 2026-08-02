"""End to end: a plan, a fleet, a dozer and a growing pile, then a reclaim campaign.

This is the test that the pieces form a system. Individually correct modules can still produce
nonsense when wired together, and the previous product shipped exactly that.
"""
from __future__ import annotations

import pytest

from bedblend.blending import tonnage_weighted_variance, vrr
from bedblend.build import build
from bedblend.design import Phase, rectangular_yard
from bedblend.reclaim import ReclaimFace, ReclaimMethod, campaign
from bedblend.relax import assert_stable
from bedblend.sectors import compare, quadrants, rollup
from bedblend.terrain import Terrain, TruckSpec
from bedblend.truck import Fleet, Payload

REPOSE = 37.0
CELL = 2.5


def _stream(n: int, *, block_size: int = 20) -> list[Payload]:
    """An incoming stream whose autocorrelation comes from the DIG SEQUENCE.

    Consecutive trucks are loaded from the same block, so consecutive grades are similar. That is
    where a stockpile's input correlation actually comes from; v1 typed it in as a variogram range.
    """
    out: list[Payload] = []
    for k in range(n):
        blk = k // block_size
        out.append(
            Payload(
                tonnes=231.0,
                grade=0.30 + 0.06 * (blk % 5) + 0.008 * ((k % 7) - 3),
                source_block=blk,
                grade_uncertainty=0.12,
            )
        )
    return out


# A full build takes tens of seconds, and every test in this file wants the same one. Running it per
# test turned the suite from under a minute into over ten. The build is deterministic, so one cached
# run is the same object every test would have produced for itself. Tests that MUTATE the result
# (reclaim drains the pile) ask for a fresh one explicitly.
_CACHE: dict[tuple[int, int], object] = {}


def _run(n_loads: int = 240, n_benches: int = 2, *, fresh: bool = False):
    key = (n_loads, n_benches)
    if not fresh and key in _CACHE:
        return _CACHE[key]
    out = _build_once(n_loads, n_benches)
    if not fresh:
        _CACHE[key] = out
    return out


def _build_once(n_loads: int, n_benches: int):
    t = Terrain.flat(64, 64, CELL)
    plan = rectangular_yard(
        n_areas=1, area_width_m=90.0, area_length_m=90.0,
        bench_height_m=8.0, n_benches=n_benches, classes=["ROM"],
    )
    plan.row_spacing_m = 10.0
    plan.tip_spacing_m = 8.0
    plan.loads_per_dozer_pass = 40
    # Access from the pit side, so the crest advances back toward the way out.
    plan.areas[0].access_xy = (90.0, 90.0)
    # The shovel is in the pit, OUTSIDE the stockpile footprint. Inside it, the first load buries
    # the loading point and every later load is correctly refused.
    fleet = Fleet.of(4, TruckSpec(), (140.0, 140.0), repose_deg=REPOSE)
    res = build(t, plan, fleet, _stream(n_loads), repose_deg=REPOSE, verify_every=50)
    return res, plan


# -- the build holds together ------------------------------------------------------------------


def test_the_build_places_material_and_the_ledger_agrees_with_the_ground():
    res, _plan = _run()
    assert res.placed, "nothing was placed at all"
    assert res.terrain.volume_m3() > 0
    res.model.assert_consistent(res.terrain)


def test_the_finished_pile_holds_the_angle_of_repose():
    """THE SPIKES. v1 finished a build with 446 cell pairs standing over the imposed angle, the worst
    at 55.9 degrees against 37. Zero is the only acceptable number."""
    res, _plan = _run()
    assert_stable(res.terrain, REPOSE)


def test_mass_is_conserved_through_the_whole_build():
    res, _plan = _run()
    truck = TruckSpec()
    expected = len(res.placed) * truck.load_volume_m3
    assert res.terrain.volume_m3() == pytest.approx(expected, rel=1e-6)


def test_the_build_is_deterministic():
    a, _p = _run(fresh=True)
    b, _p2 = _run(fresh=True)
    assert [r.placed for r in a.loads] == [r.placed for r in b.loads]
    assert [r.profile for r in a.loads] == [r.profile for r in b.loads]
    assert a.terrain.volume_m3() == pytest.approx(b.terrain.volume_m3(), rel=1e-12)


# -- the couplings that make it a system --------------------------------------------------------


def test_both_campaigns_run_and_the_base_layer_comes_first():
    res, _plan = _run()
    phases = [r.phase for r in res.placed]
    assert Phase.PADDOCK in phases
    assert Phase.EDGE in phases
    first_edge = phases.index(Phase.EDGE)
    assert all(p is Phase.PADDOCK for p in phases[:first_edge])


def test_the_dozer_runs_and_displaces_material():
    res, _plan = _run()
    assert res.dozer_passes, "the dozer never ran, so no lift was ever completed"
    assert res.model.mean_displacement_m() > 0


def test_every_placed_load_has_an_approach_and_a_departure():
    """Felipe's requirement: the truck path is drawn coming in and going away, not just the dump."""
    res, _plan = _run()
    for r in res.placed:
        assert r.approach is not None and len(r.approach.points) >= 1
        assert r.departure is not None and len(r.departure.points) >= 1


def test_placed_dumps_stay_inside_the_measured_size_envelope():
    """The geometry stays physical over a whole build, not just on a single clean call."""
    from bedblend.dump import MEASURED_LENGTH_M, MEASURED_WIDTH_M

    res, _plan = _run()
    edge = [r for r in res.placed if r.profile and r.profile.value != "paddock"]
    if not edge:
        pytest.skip("this build produced no edge dumps")
    for r in edge:
        assert r.length_m <= MEASURED_LENGTH_M[1] * 1.2
        assert r.width_m <= MEASURED_WIDTH_M[1] * 1.2


def test_refusals_are_recorded_rather_than_hidden():
    """A refused tip is the model saying the plan asked for something the pile no longer allows.

    The measured rate on this plan is about a third, and almost every refusal is "no drivable route":
    the pile grows over its own access. That is the physics behaving correctly, and it is ALSO a real
    gap in the design layer, which lays out tip positions without the access ramp that dump design
    calls for. Tracked as a finding; the assertion here is that refusals are reported with a reason
    and that the plan still gets most of its loads placed, not that the rate is zero.
    """
    res, _plan = _run()
    assert 0.0 <= res.refusal_rate < 0.5, f"refusal rate {res.refusal_rate:.0%} is implausibly high"
    for r in res.refused:
        assert r.refused_reason, "a load was refused with no reason recorded"
    assert all(
        "no drivable" in r.refused_reason or "nowhere to land" in r.refused_reason
        for r in res.refused
    ), "a load was refused for a reason other than access or the pad edge"

    # The plan is followed exactly where it can be, and the deviation is recorded where it cannot.
    exact = [r for r in res.placed if r.spot_offset_m < 1e-9]
    assert len(exact) > len(res.placed) // 2, "most loads should land exactly where planned"
    assert max(r.spot_offset_m for r in res.placed) <= 25.0 + 1e-6


# -- the characterization layer over a real build ------------------------------------------------


def test_sector_rollup_and_the_published_comparison_hold_on_a_real_build():
    res, plan = _run()
    area = plan.areas[0]
    roll = rollup(res.model, res.terrain, area)
    assert roll.n > 0
    assert roll.tonnes > 0

    obs = [(r.x_m, r.y_m, r.grade) for r in res.placed]
    for q in quadrants(area):
        c = compare(res.model, res.terrain, q, obs)
        if c.data.n < 5 or c.model.n < 5:
            continue
        assert c.model.ci[0.95] < c.data.ci[0.95], (
            f"{q.name}: model {c.model.ci[0.95]:.6f} not tighter than data {c.data.ci[0.95]:.6f}"
        )


def test_reclaim_blends_the_input_stream():
    """The whole point of a stockpile, measured: the feed out varies less than the stream in."""
    res, _plan = _run(fresh=True)
    face = ReclaimFace(
        method=ReclaimMethod.FULL_HEIGHT, position_m=0.0, direction=(1.0, 0.0),
        depth_m=10.0, width_m=200.0, max_face_m=15.0,
    )
    cuts = campaign(
        res.terrain, res.model, face, cut_tonnes=3000.0, n_cuts=30, repose_deg=REPOSE
    )
    assert len(cuts) > 3

    grades_in = [r.grade for r in res.placed]
    var_in = tonnage_weighted_variance(grades_in, [1.0] * len(grades_in))
    grades_out = [c.grade for c in cuts]
    var_out = tonnage_weighted_variance(grades_out, [c.tonnes for c in cuts])

    assert var_in > 0
    ratio = vrr(var_in, var_out)
    assert 0.0 <= ratio < 1.0, f"the pile did not reduce variance at all: VRR {ratio:.3f}"
    assert_stable(res.terrain, REPOSE)
    res.model.assert_consistent(res.terrain)
