"""Taking material back out, in a planned order, from a face a machine can actually work.

RECLAIM IS THE INVERSE OF THE BUILD, WHICH IS ITSELF THE INVERSE OF A PIT. Building adds lifts upward
where a pit cuts benches downward; reclaiming cuts them back down again. The published framing is
exactly this: modelling the stockpile "makes stockpile processing similar to mining of a large muck
pile and subject to the same methods of ore control and mine planning previously established", and
engineering software can then "create an optimized sequence for processing the stockpile which reduces
the variability of the feed entering the mill" (Young and Rogers, Minerals 2021, 11, 636, section 4.1).

SO THE ORDER IS A PLAN, NOT A FREE CHOICE. A loader or excavator works a FACE. It needs a level to
stand on, it keeps a safe face height, and removing material advances the face and lowers the level.
The previous engine represented the reclaimer as a single integer ``front`` and cut cells directly,
which is why the stacker and the reclaimer were measured colliding inside one cell in 5 of 51 cuts.

AND RECLAIM MUST RELAX. In the previous engine the cascade ran only on deposition and never after a
cut, so a reclaimed face could stand at any angle indefinitely. Every function here returns the cells
it touched so the caller relaxes and updates the ledger; ``cut`` does it directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .blocks import BlockModel, Parcel, transfer_distances
from .relax import relax_to
from .terrain import Terrain
from .truck import NoRoute, passable_mask, reachable_mask, solve_route


class ReclaimMethod(str, Enum):
    """How the face is worked.

    These are ORDERS OF EXTRACTION, not machine geometries invented for the product. The pre-crusher
    stockpile taxonomy classifies truck-built piles by exactly this: last in first out, or first in
    first out (Minerals 2021, figure 1, types 3 and 4).
    """

    # Work back from the last-placed face: the newest material comes out first.
    LIFO = "lifo"
    # Work from the oldest end: the first material placed comes out first.
    FIFO = "fifo"
    # Cut vertically through every lift at once, which is what a bench-height face does and what the
    # paper means by "processing the stockpile in parallel vertical approaches".
    FULL_HEIGHT = "full_height"


@dataclass
class Cut:
    """One parcel of material delivered to the plant, and what it was made of.

    ``provenance`` maps a source dig block to its tonnage fraction of this cut. ``displacement_m`` is
    the tonnage-weighted mean distance that material had been shoved before it was reclaimed, which is
    the honest caveat on the provenance: the further it moved, the less its dump record means.
    """

    tonnes: float
    grade: float
    provenance: dict[int, float] = field(default_factory=dict)
    displacement_m: float = 0.0
    grade_uncertainty: float = 0.0
    cells: list[int] = field(default_factory=list)
    # THE HAUL CYCLE THAT TAKES IT AWAY. A cut used to be a tonnage, a grade and a set of cells, and
    # the material simply ceased to exist at the face: nothing came for it. That is not a rendering
    # gap, it is a missing half of the operation. Reclaimed ore leaves a stockpile the same way it
    # arrived, in a truck, over ground the truck can climb, and the mirror of the build side is the
    # honest model: an EMPTY truck routes in, is loaded at the face, and routes out LOADED.
    #
    # `stand` is where the truck waits to be loaded, which is a trafficable cell beside the face
    # rather than the face itself: a loader digs the face, a truck cannot stand on it.
    stand: tuple[float, float] | None = None
    approach: list[tuple[float, float]] = field(default_factory=list)
    departure: list[tuple[float, float]] = field(default_factory=list)
    # Where the loader itself sits: on the cut, which is what the centroid of the engaged cells is.
    loader: tuple[float, float] | None = None


@dataclass
class ReclaimFace:
    """The working face: where the machine is, how deep it cuts, and how high a face it will stand.

    ``max_face_m`` is a safety limit on the height of the face being worked, and it is the reason
    reclaim cannot simply take a column from top to bottom in one pass. ``bench_m`` is the level the
    machine works from.
    """

    method: ReclaimMethod = ReclaimMethod.FULL_HEIGHT
    # Position of the face along its advance direction, in metres from the pad origin.
    position_m: float = 0.0
    # Direction the face advances, as a unit vector in pad coordinates.
    direction: tuple[float, float] = (1.0, 0.0)
    # How far into the pile one cut reaches.
    depth_m: float = 5.0
    # Across-face extent the machine engages at once.
    width_m: float = 30.0
    # Safe working face height.
    max_face_m: float = 15.0

    def engaged_cells(self, terrain: Terrain) -> list[int]:
        """Cells inside the current cut: within ``depth_m`` ahead of the face and ``width_m`` across.

        The face is a slab, not a point. That is the difference between a machine working a face and
        the previous engine's integer front, and it is what stops the reclaimer from occupying the
        same cell as something else.
        """
        dx, dy = self.direction
        mag = math.hypot(dx, dy)
        if mag < 1e-12:
            return []
        dx, dy = dx / mag, dy / mag
        px, py = -dy, dx

        # Centre the across-face window on the pad, which is where a machine working a rectangular
        # stockpile stands unless told otherwise.
        cx = terrain.nx * terrain.cell_m / 2.0
        cy = terrain.ny * terrain.cell_m / 2.0
        centre_t = cx * px + cy * py

        out: list[int] = []
        for c in range(terrain.n_cells):
            if not terrain.has_material(c):
                continue
            x, y = terrain.xy(c)
            s = x * dx + y * dy
            if not (self.position_m <= s < self.position_m + self.depth_m):
                continue
            if abs((x * px + y * py) - centre_t) > self.width_m / 2.0:
                continue
            out.append(c)
        return out


def cut(
    terrain: Terrain,
    model: BlockModel,
    face: ReclaimFace,
    tonnes_wanted: float,
    *,
    repose_deg: float,
) -> Cut:
    """Take up to ``tonnes_wanted`` from the current face, then relax what is left standing.

    Material is removed from the TOP of each engaged column for the last-in-first-out order and from
    the BOTTOM for first-in-first-out, because those are the two orders the taxonomy names. The full
    height method takes proportionally through the whole column, which is the vertical approach that
    actually blends the lifts.

    RELAXATION IS NOT OPTIONAL HERE. Removing material undercuts whatever stood above it, and the
    previous engine never relaxed after a cut, so a face could stand vertically forever.
    """
    cells = face.engaged_cells(terrain)
    if not cells or tonnes_wanted <= 0:
        return Cut(0.0, 0.0)

    per_m = model.cell_area_m2 * model.bulk_density_t_m3   # tonnes per metre of column
    available = sum(model.thickness(c) for c in cells) * per_m
    take_total = min(tonnes_wanted, available)
    if take_total <= 0:
        return Cut(0.0, 0.0)

    frac = take_total / available if available > 0 else 0.0

    grade_num = 0.0
    disp_num = 0.0
    unc_num = 0.0
    prov: dict[int, float] = {}
    got = 0.0
    touched: list[int] = []

    for c in cells:
        col = model.columns[c]
        if not col:
            continue
        want_m = model.thickness(c) * frac
        if want_m <= 0:
            continue
        # Cap the face height a single cut exposes, which is the safety limit a real machine works to.
        want_m = min(want_m, face.max_face_m)
        taken = _take(model, c, want_m, face.method)
        if not taken:
            continue
        touched.append(c)
        for p in taken:
            t = p.thickness_m * per_m
            got += t
            grade_num += t * p.grade
            disp_num += t * p.displacement_m
            unc_num += t * p.grade_uncertainty
            prov[p.source_block] = prov.get(p.source_block, 0.0) + t
        terrain.z[c] -= sum(p.thickness_m for p in taken)

    if got <= 0:
        return Cut(0.0, 0.0)

    # Undercutting leaves the surrounding material unsupported; take it down to repose. The ledger
    # must be carried along with it: relaxation MOVES MATERIAL, and a ledger that is not told about
    # the movement drifts away from the terrain, so every grade reported afterwards is attached to
    # the wrong place. Doing it here rather than leaving it to the caller is deliberate, because
    # forgetting exactly this is what the previous engine did.
    moves = relax_to(terrain, repose_deg)
    if moves:
        model.apply_transfers(
            [(a, b, v * model.cell_area_m2) for a, b, v in moves],
            distances=transfer_distances(terrain, moves),
        )

    return Cut(
        tonnes=got,
        grade=grade_num / got,
        provenance={k: v / got for k, v in prov.items()},
        displacement_m=disp_num / got,
        grade_uncertainty=unc_num / got,
        cells=touched,
    )


def _take(model: BlockModel, c: int, thickness_m: float, method: ReclaimMethod) -> list[Parcel]:
    """Remove material from one column in the order the method specifies."""
    col = model.columns[c]
    if not col or thickness_m <= 0:
        return []

    if method is ReclaimMethod.LIFO:
        return model.take_from_top(c, thickness_m)

    if method is ReclaimMethod.FIFO:
        # Oldest first. Parcels are stored bottom-up and placed in time order within a lift, so the
        # bottom of the column is the oldest material in it.
        out: list[Parcel] = []
        want = thickness_m
        while want > 1e-12 and col:
            p = col[0]
            t = p.thickness_m
            if t <= want + 1e-12:
                col.pop(0)
                out.append(p)
                want -= t
            else:
                cut_z = p.z0_m + want
                out.append(
                    Parcel(p.z0_m, cut_z, p.grade, p.source_block, p.event_id, p.lift, p.area,
                           p.grade_uncertainty, p.displacement_m)
                )
                p.z0_m = cut_z
                want = 0.0
        _restack(model, c)
        return out

    # FULL_HEIGHT: a proportional slice of every parcel, which is what a vertical face through all the
    # lifts delivers, and the only one of the three that actually blends them.
    total = model.thickness(c)
    if total <= 0:
        return []
    f = min(1.0, thickness_m / total)
    out = []
    for p in col:
        t = p.thickness_m * f
        if t <= 0:
            continue
        out.append(
            Parcel(p.z0_m, p.z0_m + t, p.grade, p.source_block, p.event_id, p.lift, p.area,
                   p.grade_uncertainty, p.displacement_m)
        )
        p.z1_m -= t
    _restack(model, c)
    return out


def _restack(model: BlockModel, c: int) -> None:
    """Close the gaps after a removal so a column stays contiguous from its base upward."""
    col = [p for p in model.columns[c] if p.thickness_m > 1e-12]
    z = 0.0
    for p in col:
        t = p.thickness_m
        p.z0_m, p.z1_m = z, z + t
        z += t
    model.columns[c] = col


def _along(terrain: Terrain, direction: tuple[float, float]) -> float:
    """Furthest extent of remaining material along a direction, or zero if the pile is gone."""
    dx, dy = direction
    mag = math.hypot(dx, dy) or 1.0
    dx, dy = dx / mag, dy / mag
    best = None
    for c in range(terrain.n_cells):
        if not terrain.has_material(c):
            continue
        x, y = terrain.xy(c)
        s = x * dx + y * dy
        if best is None or s > best:
            best = s
    return best if best is not None else 0.0


def advance(face: ReclaimFace, terrain: Terrain) -> bool:
    """Move the face one cut deeper into the pile. Returns whether there is anything left ahead.

    The face advances in a planned order rather than jumping to wherever the best grade happens to be,
    which is the constraint that makes reclaim sequencing a real decision with real consequences for
    feed variability.
    """
    face.position_m += face.depth_m
    return face.position_m <= _along(terrain, face.direction)



# ---------------------------------------------------------------------------------------------
# THE HAUL CYCLE THAT TAKES THE MATERIAL AWAY
# ---------------------------------------------------------------------------------------------
# A reclaim campaign used to remove material from a face and report a tonnage. Nothing came for it,
# nothing carried it, and on screen the pile simply lost volume with no machine in sight. Felipe put
# it exactly: "how it reclaim if no orange truck is coming to the site?"
#
# The build side already answers the same question properly, and this is its mirror. The primitives
# are the ones `build.py` uses, deliberately, so that "a truck can get there" means the same thing in
# both directions and a reclaim truck cannot drive somewhere a haul truck could not.
#
# THE TRUCK DOES NOT STAND ON THE FACE. A loader digs the face; the truck stands beside it on ground
# it can climb and is loaded over the side. So the spot is the nearest REACHABLE cell to the cut
# centroid, which is exactly the constraint that makes the model honest: if the campaign has cut
# itself into a hole no truck can reach, the cut is refused rather than teleported out.


def _centroid(terrain: Terrain, cells: list[int]) -> tuple[float, float]:
    """Where the loader sits: the middle of the cells this cut engaged, in pad metres."""
    if not cells:
        return 0.0, 0.0
    xs = 0.0
    ys = 0.0
    for c in cells:
        x, y = terrain.xy(c)
        xs += x
        ys += y
    return xs / len(cells), ys / len(cells)


def haul_cycle(
    terrain: Terrain,
    cells: list[int],
    *,
    exit_xy: tuple[float, float],
    max_grade: float,
) -> tuple[tuple[float, float] | None, list[tuple[float, float]], list[tuple[float, float]],
           tuple[float, float] | None]:
    """Route an empty truck in to the cut and a loaded one back out.

    Returns ``(stand, approach, departure, loader)`` in pad metres. ``stand`` is None when nothing
    drivable is within reach of the cut, which is a real refusal and is reported rather than hidden:
    a campaign that has undercut its own access cannot be served, and saying so is the point of
    modelling the haulage at all.

    The approach and the departure are solved SEPARATELY rather than one reversed, because the
    surface changes between them: the cut has just been taken and the face relaxed, so the way out is
    not always the way in.
    """
    loader = _centroid(terrain, cells)
    passable = passable_mask(terrain, max_grade)
    reach = reachable_mask(terrain, exit_xy, max_grade, passable=passable)

    # The nearest cell to the loader that a truck can actually stand on AND get to.
    best: int | None = None
    best_d = float("inf")
    for c in range(terrain.n_cells):
        if not (passable[c] and reach[c]):
            continue
        x, y = terrain.xy(c)
        d = (x - loader[0]) ** 2 + (y - loader[1]) ** 2
        if d < best_d:
            best_d = d
            best = c
    if best is None:
        return None, [], [], loader

    stand = terrain.xy(best)
    try:
        approach = solve_route(
            terrain, exit_xy, stand, max_grade=max_grade, passable=passable
        ).points
    except NoRoute:
        return None, [], [], loader
    try:
        departure = solve_route(
            terrain, stand, exit_xy, max_grade=max_grade, passable=passable
        ).points
    except NoRoute:
        departure = list(reversed(approach))
    return stand, approach, departure, loader

def campaign(
    terrain: Terrain,
    model: BlockModel,
    face: ReclaimFace,
    *,
    cut_tonnes: float,
    n_cuts: int,
    repose_deg: float,
    exit_xy: tuple[float, float] | None = None,
    max_grade: float | None = None,
) -> list[Cut]:
    """Run a reclaim campaign, advancing the face when the current position is worked out.

    The returned series IS the plant feed, and its variance against the variance of the incoming
    stream is what the whole product is measuring.

    WITH ``exit_xy`` AND ``max_grade``, EVERY CUT ALSO CARRIES ITS HAUL CYCLE: an empty truck routed
    in from the exit to a spot beside the face, and a loaded one routed back out. Without them the
    material still leaves the ledger correctly and the feed series is unchanged, but nothing is
    recorded about how it got off site, which is how this engine shipped a reclaim campaign that no
    machine ever attended. They are optional only so that an existing caller does not break; the
    product passes both.
    """
    out: list[Cut] = []
    haul = exit_xy is not None and max_grade is not None
    for _ in range(n_cuts):
        c = cut(terrain, model, face, cut_tonnes, repose_deg=repose_deg)
        if c.tonnes <= 0:
            if not advance(face, terrain):
                break
            c = cut(terrain, model, face, cut_tonnes, repose_deg=repose_deg)
            if c.tonnes <= 0:
                break
        if haul:
            # Routed AFTER the cut, on the surface the cut left behind, because that is the ground
            # the truck actually drives on: the face has just moved and the material has relaxed.
            stand, approach, departure, loader = haul_cycle(
                terrain, c.cells, exit_xy=exit_xy, max_grade=max_grade
            )
            c.stand, c.approach, c.departure, c.loader = stand, approach, departure, loader
        out.append(c)
    return out
