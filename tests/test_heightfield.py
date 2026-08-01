"""Method 1: the relaxation solver conserves mass exactly and reaches the imposed repose angle.

These two are the reason a reader can believe anything else the product says about the pile. A solver
that loses a fraction of a percent per dump would still draw a convincing cone, and the tonnage panels
would still show plausible numbers, and every blending metric downstream would be quietly wrong.
"""
from __future__ import annotations

import math

from bedblend.heightfield import CONVERGE_TOL_M, cascade, critical_drop, max_slope_excess


def _cone(nx=41, ny=41, spike=8.0):
    """A spike on an empty pad, small enough that its relaxed toe stays clear of the walls.

    The pad edge is a wall, so a spike large enough to reach it leaves material stacked against the
    boundary that genuinely cannot relax. That is correct behaviour, and the caller flags it, but it
    is not what these tests are measuring: at 37 degrees an 8 m spike spreads to about a 10 m radius
    on a 41-cell pad of 2 m cells, which is comfortably interior.
    """
    h = [0.0] * (nx * ny)
    h[(ny // 2) * nx + nx // 2] = spike
    return h, nx, ny


def test_mass_is_conserved_to_machine_precision():
    h, nx, ny = _cone()
    before = math.fsum(h)
    cascade(h, nx, ny, cell_m=2.0, repose_deg=37.0)
    after = math.fsum(h)
    assert abs(after - before) < 1e-9, f"relaxation moved {after - before:g} m of material"


def test_relaxed_field_stands_at_or_below_the_repose_angle():
    h, nx, ny = _cone()
    cascade(h, nx, ny, cell_m=2.0, repose_deg=37.0)
    excess = max_slope_excess(h, nx, ny, cell_m=2.0, repose_deg=37.0)
    assert excess <= 1e-6, f"a slope stands {excess:g} m steeper than the material allows"


def test_a_steeper_material_makes_a_taller_cone():
    """The repose angle must actually control the geometry, not just be recorded next to it."""
    peaks = []
    for repose in (30.0, 45.0):
        h, nx, ny = _cone()
        cascade(h, nx, ny, cell_m=2.0, repose_deg=repose)
        peaks.append(max(h))
    assert peaks[1] > peaks[0] * 1.2, f"45 degrees gave {peaks[1]:.2f} m against 30 degrees {peaks[0]:.2f} m"


def test_critical_drop_scales_with_the_diagonal_distance():
    orth, diag = critical_drop(3.0, 37.0)
    assert abs(diag / orth - math.sqrt(2.0)) < 1e-12
    assert abs(orth - 3.0 * math.tan(math.radians(37.0))) < 1e-12


def test_the_cascade_is_ordered_downslope():
    """The first transfer must leave the apex: the ordering is what the segregation solver relies on."""
    h, nx, ny = _cone()
    apex = (ny // 2) * nx + nx // 2
    moves = cascade(h, nx, ny, cell_m=2.0, repose_deg=37.0)
    assert moves, "a 30 m spike must produce an avalanche"
    assert moves[0][0] == apex, "the first cell to topple must be the highest one"


def test_a_flat_field_does_not_move():
    h = [4.0] * 100
    moves = cascade(h, 10, 10, cell_m=2.0, repose_deg=37.0)
    assert moves == []
    assert all(abs(v - 4.0) < CONVERGE_TOL_M for v in h)
