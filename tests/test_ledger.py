"""Method 8: the lot ledger keeps the mass and the provenance exact.

The provenance sum is the invariant that matters most in the whole repository. A ledger that loses or
double-counts material still draws a convincing pile and still reports plausible grades; the only way
to know it is wrong is to check the identity numerically, on every cut, on every case.
"""
from __future__ import annotations

import math

from bedblend.pile import RECLAIM_GEOMETRY, Pile
from bedblend.schema import PadSpec, TruckDump


def _pad() -> PadSpec:
    return PadSpec(nx=24, ny=16, cell_m=3.0, repose_deg=37.0)


def _dump(i: int, x: float, y: float, cu: float = 0.6, cf: float = 0.35) -> TruckDump:
    return TruckDump(event_id=i, t_s=float(i) * 90.0, truck_id="T01", source_id="DIG-001",
                     tonnes=220.0, grade_cu_pct=cu, grade_au_gpt=0.1, coarse_frac=cf,
                     moisture_pct=3.0, x_m=x, y_m=y)


def _build(n=40, sr=1.0) -> Pile:
    p = Pile(_pad())
    for i in range(n):
        x = 12.0 + (i % 12) * 3.0
        p.deposit(_dump(i, x, 24.0, cu=0.4 + 0.02 * (i % 11), cf=0.25 + 0.01 * (i % 9)), sr=sr)
    return p


def test_deposited_equals_in_pile():
    p = _build()
    assert abs(p.deposited_t - p.in_pile_t) < 1e-6


def test_the_column_tonnage_cache_never_drifts():
    p = _build()
    assert p.check_column_cache() < 1e-9


def test_mass_balance_holds_across_reclaim():
    p = _build()
    for k in range(6):
        cut, _front = p.reclaim(cut_id=k, t_s=1e4 + k * 60, target_t=700.0,
                               method="fullface", front=k % p.pad.nx)
        assert cut is not None
    assert abs(p.deposited_t - (p.in_pile_t + p.reclaimed_t)) < 1e-6


def test_provenance_fractions_sum_to_one():
    p = _build()
    front = 0
    for k in range(10):
        cut, _front = p.reclaim(cut_id=k, t_s=1e4 + k * 60, target_t=500.0,
                               method="bucketwheel", front=front)
        if cut is None:
            break
        assert abs(sum(cut.sources.values()) - 1.0) < 1e-12, cut.sources


def test_every_reclaim_geometry_conserves_mass_and_provenance():
    for method in RECLAIM_GEOMETRY:
        p = _build()
        front = 0
        for k in range(8):
            cut, _front = p.reclaim(cut_id=k, t_s=1e4 + k * 60, target_t=600.0,
                                   method=method, front=front)
            if cut is None:
                break
            assert abs(sum(cut.sources.values()) - 1.0) < 1e-12, method
            assert cut.tonnes > 0 and not math.isnan(cut.grade_cu_pct)
        assert abs(p.deposited_t - (p.in_pile_t + p.reclaimed_t)) < 1e-6, method


def test_a_full_face_cut_crosses_more_layers_than_a_loader_bite():
    """The reclaim geometry table is only meaningful if it changes the layer count."""
    counts = {}
    for method in ("fullface", "loader"):
        p = _build(n=60)
        cut, _ = p.reclaim(cut_id=0, t_s=1e5, target_t=900.0, method=method, front=6)
        assert cut is not None
        counts[method] = cut.n_layers
    assert counts["fullface"] > counts["loader"], counts


def test_segregation_moves_coarse_towards_the_toe():
    """With the solver on the low ground ends up coarser than the crest; with it off it does not.

    THE MAGNITUDE IS SMALL ON PURPOSE, and the threshold below is set from measurement rather than
    from expectation. Most of a dumped load stays where it lands: only the part standing above the
    repose surface avalanches, so segregation on a stockpile is a flank effect and not a bulk one. The
    measured index over this fixture runs from about -0.01 at Sr = 0 to about +0.04 at Sr = 0.5 and
    then saturates near +0.07, which is exactly what Gray and Thornton predict: a layer segregates
    completely within a path length of order 1/Sr, so past Sr of about one there is nothing left to
    separate and raising it further changes nothing. A test asserting a large index at high Sr would
    be asserting that the published model is wrong.
    """
    def index(sr: float) -> float:
        p = _build(n=60, sr=sr)
        toe, apex = p.toe_apex_split()
        assert toe and apex
        return (sum(p.column_coarse(c) for c in toe) / len(toe)
                - sum(p.column_coarse(c) for c in apex) / len(apex))

    off, weak, on = index(0.0), index(0.5), index(3.0)
    assert on > 0.02, f"segregation index {on:.4f} at Sr = 3 is too small to be the solver working"
    assert on > off + 0.02, f"Sr = 3 gave {on:.4f} against {off:.4f} at Sr = 0"
    assert weak > off, f"Sr = 0.5 gave {weak:.4f}, not above the Sr = 0 baseline {off:.4f}"
    assert off < 0.0 or abs(off) < 0.02, f"the Sr = 0 index {off:.4f} is larger than the geometry alone"


def test_the_segregation_effect_saturates_rather_than_growing_without_bound():
    """Past Sr of about one the flowing layer is already fully separated. This pins that behaviour."""
    def index(sr: float) -> float:
        p = _build(n=60, sr=sr)
        toe, apex = p.toe_apex_split()
        return (sum(p.column_coarse(c) for c in toe) / len(toe)
                - sum(p.column_coarse(c) for c in apex) / len(apex))

    assert index(8.0) < 4.0 * index(1.0), "the index must saturate, not scale with Sr"


def test_at_zero_segregation_every_lot_keeps_its_source_size_split():
    """The C02 kill criterion, applied at lot level where it is exact."""
    p = Pile(_pad())
    expected: dict[int, float] = {}
    for i in range(30):
        cf = 0.2 + 0.02 * (i % 13)
        expected[i] = cf
        p.deposit(_dump(i, 12.0 + (i % 10) * 3.0, 24.0, cf=cf), sr=0.0)
    worst = 0.0
    for stack in p.stacks:
        for lot in stack:
            worst = max(worst, abs(lot.coarse_frac - expected[lot.event_id]))
    assert worst < 1e-12, f"the solver changed a size split by {worst:g} while switched off"


def test_reclaiming_an_empty_pile_reports_nothing_rather_than_crashing():
    p = Pile(_pad())
    cut, front = p.reclaim(cut_id=0, t_s=0.0, target_t=100.0, method="fullface", front=0)
    assert cut is None and 0 <= front < p.pad.nx
