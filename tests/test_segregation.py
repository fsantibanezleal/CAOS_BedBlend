"""Method 4: the Gray-Thornton flowing-layer solver.

Four properties, each of which the published model requires and each of which a plausible-looking but
wrong discretisation would break:

* species mass is conserved by the march (the flux at both walls is zero);
* the concentration stays inside [0, 1], because a volume fraction that goes negative is not a number;
* fines end up at the BASE of the layer, which is the whole physical content of kinetic sieving;
* ``Sr = 0`` is exactly a passive tracer, which is what makes the C02 negative control meaningful.
"""
from __future__ import annotations

from bedblend.segregation import FlowingLayer, segregation_number


def test_species_mass_is_conserved_by_the_march():
    layer = FlowingLayer(phi0=0.5, sr=2.0, nz=32)
    before = layer.mean_phi
    for _ in range(40):
        layer.advance(0.05)
    assert abs(layer.mean_phi - before) < 1e-9


def test_concentration_stays_physical():
    layer = FlowingLayer(phi0=0.3, sr=6.0, nz=32)
    for _ in range(80):
        layer.advance(0.05)
        assert all(0.0 - 1e-12 <= p <= 1.0 + 1e-12 for p in layer.phi)


def test_fines_drain_to_the_base():
    """Kinetic sieving: small particles percolate down and lever the large ones up."""
    layer = FlowingLayer(phi0=0.5, sr=3.0, nz=32)
    for _ in range(40):
        layer.advance(0.05)
    base = sum(layer.phi[:8]) / 8
    top = sum(layer.phi[-8:]) / 8
    assert base > top + 0.4, f"base {base:.3f} is not fine-rich against the surface {top:.3f}"


def test_a_fully_segregated_layer_stops_segregating():
    """The phi(1-phi) flux shuts off at a pure phase; running longer must not overshoot."""
    layer = FlowingLayer(phi0=0.5, sr=8.0, nz=16)
    for _ in range(200):
        layer.advance(0.05)
    assert layer.phi[0] > 0.98 and layer.phi[-1] < 0.02
    assert abs(layer.mean_phi - 0.5) < 1e-9


def test_zero_segregation_number_is_a_passive_tracer():
    """The C02 negative control depends on this holding EXACTLY, not approximately."""
    layer = FlowingLayer(phi0=0.37, sr=0.0, nz=32)
    for _ in range(50):
        layer.advance(0.1)
    assert all(p == 0.37 for p in layer.phi)
    dep, rest = layer.split_base(0.4)
    assert dep == 0.37 and rest == 0.37


def test_split_base_conserves_species_mass():
    layer = FlowingLayer(phi0=0.6, sr=2.5, nz=32)
    for _ in range(10):
        layer.advance(0.05)
    before = layer.mean_phi
    f = 0.35
    dep, rest = layer.split_base(f)
    assert abs(f * dep + (1.0 - f) * rest - before) < 1e-9


def test_segregation_number_is_the_published_ratio():
    """Equation (3.19): Sr = q L / (H U)."""
    assert abs(segregation_number(0.02, 30.0, 0.3, 2.0) - (0.02 * 30.0) / (0.3 * 2.0)) < 1e-12
    assert segregation_number(0.02, 30.0, 0.0, 2.0) == 0.0
