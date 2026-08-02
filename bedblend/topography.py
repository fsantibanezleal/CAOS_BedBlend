"""Ground that is not flat, and the fill types that go with it.

A STOCKPILE IS CLASSIFIED BY THE GROUND IT IS BUILT ON. The published taxonomy has five types, and
only one of them is a flat pad (Young and Rogers, Minerals 2021, 11, 636, figure 2, adapted from
Hawley and Cunning's dump and stockpile design guidelines):

    heaped fill        free-standing on flat prepared ground
    sidehill fill      built against a hillside, keyed into the slope
    valley fill        built along a valley floor, confined on two sides
    cross-valley fill  built ACROSS a drainage, so the fill dams the valley
    ridge crest fill   built along a ridge, shedding to both sides

Modelling only the flat case is modelling one fifth of the subject, and it hides the mechanic that
makes topography matter: the ground decides where equipment can go before a single load is placed.
On a sidehill the access is along the contour, not up the slope; in a valley the fill is confined and
the same tonnage stands far higher; across a drainage the toe advances into falling ground and the
run-out is longer on one side than the other.

WHAT THESE FUNCTIONS ARE. Analytic ground surfaces, parameterised and seeded, for building scenarios
on. They are deliberately simple shapes rather than imported survey data: a scenario has to be
reproducible bit for bit, and the point being made is about the INTERACTION between construction and
relief, which a clean shape shows more clearly than a noisy real one. Real survey ground loads through
``Terrain.from_ground`` and that path is unchanged.

THE ONE THING TO WATCH. ``Terrain`` keeps the original ground in ``z0``, so "how much material is
here" stays a different question from "how high is the surface". On sloping ground those two answers
diverge immediately, and code that confuses them will report a hillside as a stockpile.
"""
from __future__ import annotations

import math
from enum import Enum

from .stream import Xorshift
from .terrain import Terrain


class FillType(str, Enum):
    """The five stockpile fill types, named as the source names them."""

    HEAPED = "heaped"
    SIDEHILL = "sidehill"
    VALLEY = "valley"
    CROSS_VALLEY = "cross_valley"
    RIDGE_CREST = "ridge_crest"


def _apply_roughness(z: list[float], nx: int, ny: int, amp_m: float, seed: int) -> list[float]:
    """Add smooth low-amplitude relief so the ground is not suspiciously perfect.

    Two octaves of value noise, smoothed, rather than per-cell white noise. White noise would make
    every cell locally steep and the trafficability mask would come out as static, which is a
    modelling artefact rather than terrain.
    """
    if amp_m <= 0:
        return z
    rng = Xorshift(seed)
    out = list(z)
    # Long wavelengths: 40 m and 20 m at a 2.5 m cell. Short-wavelength noise of the same
    # amplitude produces gradients above the equipment limit, so the trafficability mask comes
    # out as static and the terrain reads as undrivable everywhere for no physical reason.
    for octave, cells in ((1.0, 16), (0.5, 8)):
        gw, gh = max(2, nx // cells + 2), max(2, ny // cells + 2)
        grid = [rng.normal() for _ in range(gw * gh)]
        for j in range(ny):
            for i in range(nx):
                gx, gy = i / cells, j / cells
                x0, y0 = int(gx), int(gy)
                fx, fy = gx - x0, gy - y0
                # Smoothstep, so the interpolation has no visible grid creases.
                sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
                x1, y1 = min(x0 + 1, gw - 1), min(y0 + 1, gh - 1)
                a = grid[y0 * gw + x0] * (1 - sx) + grid[y0 * gw + x1] * sx
                b = grid[y1 * gw + x0] * (1 - sx) + grid[y1 * gw + x1] * sx
                out[j * nx + i] += amp_m * octave * (a * (1 - sy) + b * sy)
    return out


def ground(
    fill: FillType,
    nx: int,
    ny: int,
    cell_m: float,
    *,
    relief_m: float = 25.0,
    roughness_m: float = 0.0,
    seed: int = 1,
) -> Terrain:
    """Original ground for a given fill type, as a ``Terrain`` with ``z == z0``.

    ``relief_m`` is the total vertical range of the landform: the drop across a sidehill, the depth of
    a valley, the height of a ridge. It is the single number that decides whether the topography is a
    detail or the dominant constraint.
    """
    w, h = nx * cell_m, ny * cell_m
    z = [0.0] * (nx * ny)

    for j in range(ny):
        y = (j + 0.5) * cell_m
        for i in range(nx):
            x = (i + 0.5) * cell_m
            u, v = x / w, y / h
            if fill is FillType.HEAPED:
                e = 0.0
            elif fill is FillType.SIDEHILL:
                # A planar hillside falling across the pad, steeper at the top than the toe so the
                # bench cut into it reads as a bench rather than as a ramp.
                e = relief_m * (1.0 - v) ** 1.3
            elif fill is FillType.VALLEY:
                # A trough running along +x, confined on both sides.
                e = relief_m * (2.0 * abs(v - 0.5)) ** 1.6
            elif fill is FillType.CROSS_VALLEY:
                # A drainage running across the pad in +y, with the floor falling along it. The fill
                # is placed ACROSS the drainage, so its toe advances into ground that is itself
                # dropping away, which is why one side runs out much further than the other.
                trough = relief_m * 0.75 * (2.0 * abs(u - 0.5)) ** 1.6
                fall = relief_m * 0.35 * (1.0 - v)
                e = trough + fall
            else:  # RIDGE_CREST
                # A ridge along +x, shedding to both sides.
                e = relief_m * (1.0 - (2.0 * abs(v - 0.5)) ** 1.6)
            z[j * nx + i] = e

    if roughness_m > 0:
        z = _apply_roughness(z, nx, ny, roughness_m, seed)
        # Roughness must not push the ground below zero, which would read as excavation nobody did.
        lo = min(z)
        if lo < 0:
            z = [v - lo for v in z]

    return Terrain.from_ground(nx, ny, cell_m, z)


def relief_stats(terrain: Terrain) -> dict[str, float]:
    """Range, mean and steepest gradient of the ORIGINAL ground.

    Reported against ``z0`` rather than ``z`` on purpose: once material is placed, the surface stops
    describing the landform, and a product that shows "site relief" computed off the live surface is
    reporting the pile as if it were geology.
    """
    z0 = terrain.z0
    lo, hi = min(z0), max(z0)
    worst = 0.0
    for c in range(terrain.n_cells):
        i, j = terrain.ij(c)
        for di, dj, run in (
            (1, 0, terrain.cell_m), (0, 1, terrain.cell_m),
            (1, 1, terrain.cell_m * math.sqrt(2.0)), (1, -1, terrain.cell_m * math.sqrt(2.0)),
        ):
            ni, nj = i + di, j + dj
            if 0 <= ni < terrain.nx and 0 <= nj < terrain.ny:
                worst = max(worst, abs(z0[c] - z0[terrain.idx(ni, nj)]) / run)
    return {
        "min_m": lo,
        "max_m": hi,
        "relief_m": hi - lo,
        "mean_m": sum(z0) / len(z0),
        "max_gradient": worst,
        "max_slope_deg": math.degrees(math.atan(worst)),
    }


def buildable_fraction(terrain: Terrain, max_grade: float) -> float:
    """Fraction of the ORIGINAL ground a truck could already drive on, before anything is built.

    The number that says whether a site needs preparation. On a flat pad it is one; on a sidehill at
    the equipment limit it can be a small fraction, and every load placed there has to reach a working
    area that was cut or filled first. Showing it makes the difference between the five fill types
    quantitative rather than pictorial.
    """
    n = terrain.n_cells
    if n == 0:
        return 0.0
    probe = Terrain(terrain.nx, terrain.ny, terrain.cell_m, list(terrain.z0), list(terrain.z0))
    return sum(1 for c in range(n) if probe.gradient(c) <= max_grade) / n
