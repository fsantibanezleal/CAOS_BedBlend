"""The raw ledger: what material is where, where it came from, and how sure we are.

THE SUPPORT IS THE TRUCKLOAD, because that is the unit that was measured, hauled and placed. Two
independent studies fix the resolution at or below half a load: a reference model "at the resolution of
1/2 of a truck load (15 to 20 tonne blocks), that is, a 2.5m by 2.5m by 2.5 m cell size" (Neufeld,
Lyall and Deutsch, CCG Report 8 paper 306, 2006), and a stockpile block model at 5 m blocks
interpolated on 15 m centres (Young and Rogers, Minerals 2021, 11, 636).

WHY PER-COLUMN PARCELS RATHER THAN A FIXED 3-D LATTICE. A parcel records the interval of a column that
one placement occupies, so a lift is represented exactly rather than being rounded onto a vertical
grid. The published inference method is coarser than this on purpose: "since the accuracy of each
elevation value was limited to the value of the bench level, each bench was modeled as a
two-dimensional plane". That is a limitation of inferring from sparse survey data, not of the
underlying object, and a simulation that knows its own ground truth should not copy it. ``to_blocks``
exports onto a regular lattice when a block model is what is wanted, so the coarser view is available
without being the only view.

THE QUANTIFIED CASE FOR TRACKING AT THIS SUPPORT, which belongs in the product's own text: sampling
every truck gives a density equal to the truck's capacity, 100 to 400 t per sample, against 175,000 t
per sample for a conventional stockpile campaign. Three orders of magnitude.

AND THE UNCERTAINTY THIS LEDGER MUST CARRY, because the previous product did not. Two independent
sources of error, both published:

  * The grade on a load is already uncertain before the truck moves. Misclassification of ore to waste
    or waste to ore from sampling error alone is "commonly between 5% and 20%" for base and precious
    metal mines, with a further 9 to 19 percent ore loss from blast movement and dilution.
  * The location degrades after placement. Dozers "frequently displace stockpiled material from its
    original dump location, making it hard to know where material is located within the stockpile",
    mixing it "in intractable ways".

So a parcel carries a grade uncertainty and a displacement. Reporting provenance to 1e-12, as v1 did,
states a precision that belongs to the simulation and not to any real operation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .terrain import Terrain


@dataclass
class Parcel:
    """One placement's contribution to one column, as a vertical interval.

    ``displacement_m`` accumulates how far this material has been shoved since it was tipped. It
    starts at zero and grows every time a dozer moves it, which is what turns a provenance claim from
    an assertion into an estimate with a stated spread.
    """

    z0_m: float
    z1_m: float
    grade: float
    source_block: int
    event_id: int
    lift: int
    area: str
    grade_uncertainty: float = 0.0
    displacement_m: float = 0.0

    @property
    def thickness_m(self) -> float:
        return max(0.0, self.z1_m - self.z0_m)


@dataclass
class BlockModel:
    """Per-column parcel stacks over the same pad as the terrain.

    Invariant, asserted by the tests: for every column, the total parcel thickness equals the terrain's
    material thickness. If the two ever disagree, either material was placed without being recorded or
    recorded without being placed, and every grade the product reports downstream is wrong.
    """

    nx: int
    ny: int
    cell_m: float
    columns: list[list[Parcel]] = field(default_factory=list)
    bulk_density_t_m3: float = 1.9

    @classmethod
    def over(cls, terrain: Terrain, *, bulk_density_t_m3: float = 1.9) -> BlockModel:
        return cls(
            nx=terrain.nx,
            ny=terrain.ny,
            cell_m=terrain.cell_m,
            columns=[[] for _ in range(terrain.n_cells)],
            bulk_density_t_m3=bulk_density_t_m3,
        )

    @property
    def cell_area_m2(self) -> float:
        return self.cell_m * self.cell_m

    # -- recording --------------------------------------------------------------------------

    def record(
        self,
        terrain: Terrain,
        cells: list[int],
        added_m: list[float],
        *,
        grade: float,
        source_block: int,
        event_id: int,
        lift: int,
        area: str,
        grade_uncertainty: float = 0.0,
    ) -> None:
        """Record a placement.

        ``added_m`` must be the thickness the dump operator ADDED, and the terrain must already have
        been updated, because the new material occupies the top of each column. Passing the pre-dump
        terrain would file every parcel one load too low.
        """
        for c, dz in zip(cells, added_m, strict=True):
            if dz <= 0.0:
                continue
            top = terrain.z[c]
            self.columns[c].append(
                Parcel(
                    z0_m=top - dz,
                    z1_m=top,
                    grade=grade,
                    source_block=source_block,
                    event_id=event_id,
                    lift=lift,
                    area=area,
                    grade_uncertainty=grade_uncertainty,
                )
            )

    # -- the operations that move material ---------------------------------------------------

    def apply_transfers(
        self, transfers: list[tuple[int, int, float]], *, distances: list[float] | None = None
    ) -> None:
        """Move material between columns, taking it off the TOP of the source.

        Used for both dozer passes and relaxation transfers. Material comes off the top because that
        is what a blade and an avalanche both engage: taking it from the bottom would invert the
        stratigraphy the whole product exists to show.

        ``distances`` accumulate onto the moved parcels, which is how displacement uncertainty grows.
        """
        for k, (src, dst, vol_m3) in enumerate(transfers):
            if vol_m3 <= 0 or src == dst:
                continue
            want = vol_m3 / self.cell_area_m2      # thickness to remove
            moved = self._take_from_top(src, want)
            d = distances[k] if distances is not None else 0.0
            for p in moved:
                p.displacement_m += d
            self._stack_onto(dst, moved)

    def _take_from_top(self, c: int, thickness_m: float) -> list[Parcel]:
        """Remove ``thickness_m`` from the top of a column and return it, splitting a parcel if needed."""
        out: list[Parcel] = []
        want = thickness_m
        col = self.columns[c]
        while want > 1e-12 and col:
            p = col[-1]
            t = p.thickness_m
            if t <= want + 1e-12:
                col.pop()
                out.append(p)
                want -= t
            else:
                # Split: the upper slice leaves, the lower slice stays.
                cut = p.z1_m - want
                out.append(
                    Parcel(cut, p.z1_m, p.grade, p.source_block, p.event_id, p.lift, p.area,
                           p.grade_uncertainty, p.displacement_m)
                )
                p.z1_m = cut
                want = 0.0
        out.reverse()   # preserve original stacking order for the destination
        return out

    def _stack_onto(self, c: int, parcels: list[Parcel]) -> None:
        col = self.columns[c]
        z = col[-1].z1_m if col else self.base_z(c)
        for p in parcels:
            t = p.thickness_m
            p.z0_m, p.z1_m = z, z + t
            z += t
            col.append(p)

    def base_z(self, c: int) -> float:
        """Bottom of a column. Zero here; the terrain's own ground offset is applied by the caller."""
        return self.columns[c][0].z0_m if self.columns[c] else 0.0

    # -- reading ----------------------------------------------------------------------------

    def thickness(self, c: int) -> float:
        return sum(p.thickness_m for p in self.columns[c])

    def tonnes(self, c: int) -> float:
        return self.thickness(c) * self.cell_area_m2 * self.bulk_density_t_m3

    def column_grade(self, c: int) -> float | None:
        """Tonnage-weighted mean grade of a column, or ``None`` where there is no material."""
        t = w = 0.0
        for p in self.columns[c]:
            t += p.thickness_m * p.grade
            w += p.thickness_m
        return t / w if w > 0 else None

    def grade_field(self) -> list[float | None]:
        return [self.column_grade(c) for c in range(self.nx * self.ny)]

    def total_tonnes(self) -> float:
        return sum(self.tonnes(c) for c in range(self.nx * self.ny))

    def mean_displacement_m(self) -> float:
        """Tonnage-weighted mean displacement over the whole model.

        The headline honesty number: how far, on average, material has been moved from where its dump
        record says it was tipped.
        """
        num = den = 0.0
        for col in self.columns:
            for p in col:
                num += p.thickness_m * p.displacement_m
                den += p.thickness_m
        return num / den if den > 0 else 0.0

    # -- export -----------------------------------------------------------------------------

    def to_blocks(self, dz_m: float = 5.0) -> list[tuple[int, int, int, float, float]]:
        """Regular block model: ``(i, j, k, grade, tonnes)`` on a lattice of height ``dz_m``.

        This is the form the published method produces and the form a mine planning package consumes.
        It is a VIEW, computed on demand, so the coarse representation never becomes the stored truth.
        """
        out: list[tuple[int, int, int, float, float]] = []
        for c in range(self.nx * self.ny):
            col = self.columns[c]
            if not col:
                continue
            i, j = c % self.nx, c // self.nx
            top = col[-1].z1_m
            k = 0
            while k * dz_m < top - 1e-9:
                lo, hi = k * dz_m, (k + 1) * dz_m
                num = den = 0.0
                for p in col:
                    overlap = min(p.z1_m, hi) - max(p.z0_m, lo)
                    if overlap > 0:
                        num += overlap * p.grade
                        den += overlap
                if den > 0:
                    out.append((i, j, k, num / den, den * self.cell_area_m2 * self.bulk_density_t_m3))
                k += 1
        return out

    def assert_consistent(self, terrain: Terrain, tol_m: float = 1e-6) -> None:
        """Every column's parcels must add up to the material the terrain says is there.

        A disagreement means material was placed without being recorded or recorded without being
        placed, and every grade downstream is then wrong. Cheap to check and worth checking often.
        """
        worst = 0.0
        worst_c = -1
        for c in range(self.nx * self.ny):
            d = abs(self.thickness(c) - terrain.thickness(c))
            if d > worst:
                worst, worst_c = d, c
        if worst > tol_m:
            raise AssertionError(
                f"the ledger and the terrain disagree by {worst:.6g} m at cell {worst_c}: "
                f"ledger {self.thickness(worst_c):.6g} m, terrain {terrain.thickness(worst_c):.6g} m"
            )


def transfer_distances(terrain: Terrain, transfers: list[tuple[int, int, float]]) -> list[float]:
    """Straight-line distance for each transfer, for accumulating displacement onto parcels."""
    out: list[float] = []
    for a, b, _ in transfers:
        ax, ay = terrain.xy(a)
        bx, by = terrain.xy(b)
        out.append(math.hypot(bx - ax, by - ay))
    return out
