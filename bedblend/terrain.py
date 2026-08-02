"""The ground the stockpile is built on, and the constraint it places on the machines.

WHAT THIS IS. An elevation field over a pad, plus the two things derived from it that decide what a
machine is allowed to do next: the CREST of the current working level, and TRAFFICABILITY.

WHY IT EXISTS AT ALL. The previous engine had no such thing, and that omission is the root defect of
the product. Without a crest there is no face, so a truck dump cannot cascade and the four measured
dump profiles cannot arise. Without trafficability the pile does not constrain its own construction,
so material can be placed at any coordinate, including repeatedly at one point, which is physically
impossible: placing a load raises the local surface, and the next truck cannot occupy the space the
last load now fills.

THE GOVERNING IDEA. A truck-built stockpile is the inverse of an open pit. The pit cuts benches
downward; the stockpile adds lifts upward. The primitives are the same: a working level, a face
standing at the angle of repose, a berm, an overall slope flatter than the face, and a ramp of a given
width and gradient that gives equipment access to the next level. Waste-dump design states the
construction directly: a footprint base is created by deep dumping and then ramped up by a determined
lift height, with access to successive lifts by ramps of suitable width and gradient
(Cogent Engineering 4(1), 1387955, doi:10.1080/23311916.2017.1387955).

THE PILE STARTS EMPTY. ``Terrain`` is initialised from the original ground, flat or not, and the first
loads are placed while driving on that ground. Everything after that is a consequence of what has
already been placed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 8-neighbourhood, orthogonals first then diagonals. Matching the relaxation solver's ordering matters:
# a 4-neighbourhood produces visibly square cones, which a reader correctly reads as a bug.
_OFFSETS: tuple[tuple[int, int], ...] = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)

# A cell counts as carrying material only above this. Exactly zero is the bare pad, and the distinction
# is not cosmetic: colouring a zero-height cell as material at grade zero made the empty pad read as a
# full pile in a shipped release.
EMPTY_M = 1e-4


@dataclass(frozen=True)
class TruckSpec:
    """The machine whose dimensions set the scale of everything placed.

    A dumped load is not an abstract quantity landing on a cell. Its footprint is set by the truck:
    "The height, length and width of the heap are dependent on the respective height, width and length
    of the haul truck used" (Young and Rogers, Minerals 2021, 11, 636, figure 11).

    Defaults are the CAT 793F, the machine measured in the companion dumping study: payload about
    231 t, inside bed width 7334 mm (Young and Rogers, Mining 2022, 2, 86-102,
    doi:10.3390/mining2010006). Body length and dump height are approximate published figures for the
    class and are exposed as parameters rather than presented as exact.
    """

    name: str = "CAT 793F"
    payload_t: float = 231.0
    bed_width_m: float = 7.334
    body_length_m: float = 12.9
    dump_height_m: float = 6.5
    # Loose bulk density of blasted ore. 1.6 to 2.2 t/m3 is the usual handbook band for hard rock;
    # the value is a parameter because it sets the volume of every load placed.
    loose_density_t_m3: float = 1.9

    @property
    def load_volume_m3(self) -> float:
        return self.payload_t / self.loose_density_t_m3


@dataclass
class Terrain:
    """Elevation over a regular pad, with the original ground retained.

    ``z`` is the current surface and ``z0`` the ground it started from, both row-major with
    ``idx = j * nx + i``. Keeping ``z0`` is what lets the model answer "how much material is here",
    which is not the same question as "how high is the surface" once the pad is not flat.
    """

    nx: int
    ny: int
    cell_m: float
    z: list[float]
    z0: list[float]

    @classmethod
    def flat(cls, nx: int, ny: int, cell_m: float, base_m: float = 0.0) -> Terrain:
        n = nx * ny
        return cls(nx=nx, ny=ny, cell_m=cell_m, z=[base_m] * n, z0=[base_m] * n)

    @classmethod
    def from_ground(cls, nx: int, ny: int, cell_m: float, ground: list[float]) -> Terrain:
        if len(ground) != nx * ny:
            raise ValueError(f"ground has {len(ground)} cells, pad is {nx}x{ny}={nx * ny}")
        return cls(nx=nx, ny=ny, cell_m=cell_m, z=list(ground), z0=list(ground))

    # -- geometry helpers -------------------------------------------------------------------

    @property
    def n_cells(self) -> int:
        return self.nx * self.ny

    def idx(self, i: int, j: int) -> int:
        return j * self.nx + i

    def ij(self, c: int) -> tuple[int, int]:
        return c % self.nx, c // self.nx

    def xy(self, c: int) -> tuple[float, float]:
        """Cell CENTRE in metres. Centres, not corners, because every distance in the dump operators
        is measured between a truck position and a cell, and a half-cell bias there is a systematic
        error in the placed footprint."""
        i, j = self.ij(c)
        return (i + 0.5) * self.cell_m, (j + 0.5) * self.cell_m

    def cell_at(self, x_m: float, y_m: float) -> int | None:
        i = int(x_m // self.cell_m)
        j = int(y_m // self.cell_m)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return self.idx(i, j)
        return None

    def neighbours(self, c: int) -> list[int]:
        i, j = self.ij(c)
        out: list[int] = []
        for di, dj in _OFFSETS:
            ni, nj = i + di, j + dj
            if 0 <= ni < self.nx and 0 <= nj < self.ny:
                out.append(self.idx(ni, nj))
        return out

    # -- what is actually here --------------------------------------------------------------

    def thickness(self, c: int) -> float:
        """Material above original ground, in metres."""
        return self.z[c] - self.z0[c]

    def has_material(self, c: int) -> bool:
        return self.thickness(c) > EMPTY_M

    def volume_m3(self) -> float:
        a = self.cell_m * self.cell_m
        return sum(self.z[k] - self.z0[k] for k in range(self.n_cells)) * a

    # -- slope, crest, trafficability -------------------------------------------------------

    def gradient(self, c: int) -> float:
        """Steepest gradient at ``c`` as a rise over run, against the 8-neighbourhood.

        Returned as a gradient rather than an angle because every consumer compares it against a
        tangent, and converting to degrees and back loses that for no benefit.
        """
        i, j = self.ij(c)
        zc = self.z[c]
        worst = 0.0
        for k, (di, dj) in enumerate(_OFFSETS):
            ni, nj = i + di, j + dj
            if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                continue
            run = self.cell_m * (math.sqrt(2.0) if k >= 4 else 1.0)
            drop = zc - self.z[self.idx(ni, nj)]
            worst = max(worst, abs(drop) / run)
        return worst

    def slope_deg(self, c: int) -> float:
        return math.degrees(math.atan(self.gradient(c)))

    def trafficable(self, c: int, max_grade: float) -> bool:
        """Can a haul truck stand on this cell.

        ``max_grade`` is a rise over run. Operational guidance is that trucks should not travel on
        slopes approaching the angle of repose, and a commonly repeated rule of thumb is roughly the
        repose gradient divided by 1.5. That figure is NOT a measured constant and is deliberately a
        caller-supplied parameter here rather than a hidden default, so the product can state where the
        number came from instead of implying a law.
        """
        return self.gradient(c) <= max_grade

    def trafficable_mask(self, max_grade: float) -> list[bool]:
        return [self.trafficable(c, max_grade) for c in range(self.n_cells)]

    def crest_cells(self, min_drop_m: float) -> list[int]:
        """Cells on the edge of the current face: material here, and a drop of at least ``min_drop_m``
        to some neighbour.

        THE CREST IS WHY THIS MODULE EXISTS. Every edge dump is placed relative to it, and the measured
        result is that the truck's distance to the crest selects which of the four dump profiles forms:
        dumping far from the crest gives a sloughed heap, while dumping against it gives a comet, oval
        or rectangular profile (Mining 2022, section 4.2). Without a crest there is no such distance and
        no such choice, which is why the previous engine could only ever place one shape.
        """
        out: list[int] = []
        for c in range(self.n_cells):
            if not self.has_material(c):
                continue
            zc = self.z[c]
            for n in self.neighbours(c):
                if zc - self.z[n] >= min_drop_m:
                    out.append(c)
                    break
        return out

    def outward_normal(self, c: int) -> tuple[float, float]:
        """Unit vector pointing DOWN the face at ``c``, in pad coordinates.

        This is the direction an edge-dumped load runs along. The measured rule is that the volume of
        influence of the truck "runs perpendicular to the tangent of the dump location" (Minerals 2021,
        figure 13), which is this vector: perpendicular to the crest tangent is the same as along the
        outward normal.

        Computed as the negated elevation gradient by central differences, so it is the true steepest
        descent rather than a snap to one of eight compass directions. A flat cell has no face and
        returns ``(0, 0)``; the caller decides what that means, which is usually that the load is a
        paddock heap rather than an edge dump.
        """
        i, j = self.ij(c)
        i_lo, i_hi = max(i - 1, 0), min(i + 1, self.nx - 1)
        j_lo, j_hi = max(j - 1, 0), min(j + 1, self.ny - 1)
        # Descent is the negative gradient. Spans count the cells actually crossed so the value stays
        # correct on the boundary, where the stencil is one-sided.
        dx_span = (i_hi - i_lo) * self.cell_m
        dy_span = (j_hi - j_lo) * self.cell_m
        gx = -(self.z[self.idx(i_hi, j)] - self.z[self.idx(i_lo, j)]) / dx_span if dx_span > 0 else 0.0
        gy = -(self.z[self.idx(i, j_hi)] - self.z[self.idx(i, j_lo)]) / dy_span if dy_span > 0 else 0.0
        mag = math.hypot(gx, gy)
        if mag < 1e-12:
            return 0.0, 0.0
        return gx / mag, gy / mag

    def copy(self) -> Terrain:
        return Terrain(self.nx, self.ny, self.cell_m, list(self.z), list(self.z0))
