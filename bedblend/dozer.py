"""The dozer: the machine that completes a lift, restores access, and destroys provenance.

WITHOUT THIS MODULE NOTHING EVER FINISHES A BENCH. Paddock dumping leaves a field of separate heaps.
Something has to turn that field into a drivable working level with a crest to dump over, and that
something is the dozer. The previous engine had no such operator, which is why it had no mechanism by
which a lift was ever completed or the next lift became reachable.

WHAT THE SOURCES SAY IT DOES.

  * It decides the traffic. "Material delivered to stockpiles will be dumped and spread by dozer in
    shallow lifts, and dozer operators determine how haul trucks access the dump or stockpile and in
    what order" (Baffinland, Life-of-Mine Waste Rock Management Plan, 2017).
  * It works on a fixed cadence, not continuously. "The material is dozed up the pile after two rows
    have been dumped" (Neufeld, Lyall and Deutsch, CCG Report 8 paper 306, 2006, for Anglo American).
  * During the edge campaign it keeps the cascade clean and the site safe. Dozers "ensure that
    material is cascaded without clumping, ensure compaction and maintain safety berms during
    operation" (Young and Rogers, Minerals 2021, 11, 636, section 3.3).
  * In the paddock campaign it works the edges. Material dumped that way "is only handled by dozers or
    other heavy equipment in areas around the perimeter of the stockpile" (same, section 3.2).

AND THE PART THAT IS AN HONESTY REQUIREMENT RATHER THAN A FEATURE. Those actions "mix the material
from its initial dumping location in intractable ways", and more bluntly: dozers "frequently displace
stockpiled material from its original dump location, making it hard to know where material is located
within the stockpile" (same paper, sections 3.3 and 1.3).

That sentence is why this module reports displacement rather than merely performing it. The previous
product printed provenance fractions summing to one within 1e-12 and presented the number as an
answer. With a dozer in the model that precision is a property of the simulation and not of the world.
Every pass here returns the distance material actually travelled, so the block ledger can carry a
displacement uncertainty instead of implying a certainty no real operation has.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .design import Area
from .terrain import Terrain

# Typical efficient push distance for a large track dozer. Beyond roughly this the operator would
# rehandle rather than keep pushing, so it bounds how far one pass can move material. It is an
# operational figure, not a measured constant, and it is a parameter everywhere it is used.
DEFAULT_PUSH_M = 40.0

# Blade capacity per pass, as a volume. Used to bound how much a single cell can shed in one pass so
# that levelling is progressive rather than instantaneous.
DEFAULT_BLADE_M3 = 30.0


@dataclass
class DozerPass:
    """What one pass moved, and how far it moved it.

    ``transfers`` are ``(from_cell, to_cell, volume_m3)``. The block ledger consumes them to move
    provenance along with the material, which is the only way the ledger can stay honest: material
    that was dozed thirty metres is no longer where its dump record says it is.
    """

    transfers: list[tuple[int, int, float]] = field(default_factory=list)
    volume_moved_m3: float = 0.0
    # Volume-weighted mean and the worst case, both in metres. These are the displacement uncertainty.
    mean_displacement_m: float = 0.0
    max_displacement_m: float = 0.0
    cells_touched: int = 0

    def merge(self, other: DozerPass) -> DozerPass:
        v = self.volume_moved_m3 + other.volume_moved_m3
        mean = (
            (self.mean_displacement_m * self.volume_moved_m3
             + other.mean_displacement_m * other.volume_moved_m3) / v
            if v > 0 else 0.0
        )
        return DozerPass(
            transfers=self.transfers + other.transfers,
            volume_moved_m3=v,
            mean_displacement_m=mean,
            max_displacement_m=max(self.max_displacement_m, other.max_displacement_m),
            cells_touched=self.cells_touched + other.cells_touched,
        )


def _finalise(terrain: Terrain, transfers: list[tuple[int, int, float]]) -> DozerPass:
    """Summarise a set of transfers into a pass record, computing the displacement statistics."""
    if not transfers:
        return DozerPass()
    total = 0.0
    weighted = 0.0
    worst = 0.0
    touched: set[int] = set()
    for a, b, v in transfers:
        ax, ay = terrain.xy(a)
        bx, by = terrain.xy(b)
        d = math.hypot(bx - ax, by - ay)
        total += v
        weighted += v * d
        worst = max(worst, d)
        touched.add(a)
        touched.add(b)
    return DozerPass(
        transfers=transfers,
        volume_moved_m3=total,
        mean_displacement_m=weighted / total if total > 0 else 0.0,
        max_displacement_m=worst,
        cells_touched=len(touched),
    )


def _cells_of(terrain: Terrain, area: Area) -> list[int]:
    out: list[int] = []
    for c in range(terrain.n_cells):
        x, y = terrain.xy(c)
        if area.contains(x, y):
            out.append(c)
    return out


def level(
    terrain: Terrain,
    area: Area,
    *,
    target_z: float | None = None,
    push_m: float = DEFAULT_PUSH_M,
    blade_m3: float = DEFAULT_BLADE_M3,
    tolerance_m: float = 0.05,
) -> DozerPass:
    """Spread the heaps in ``area`` into a level working floor, conserving mass exactly.

    THIS IS THE OPERATION THAT MAKES THE NEXT LIFT POSSIBLE. A paddock campaign leaves a lattice of
    separate frustums with hollows between them; a truck cannot drive on that, and there is no
    continuous crest to dump over. Levelling turns it into a bench floor.

    ``target_z`` defaults to the mass-conserving mean over the area, which is the elevation the
    material already there would reach if spread flat. Passing an explicit value is how a caller
    builds to a designed bench top instead.

    Material moves from cells above the target to the NEAREST cells below it, within ``push_m``. The
    nearest-first rule matters for the ledger as much as for the geometry: a dozer shoves material a
    short distance, so provenance smears locally rather than teleporting across the pile, and the
    displacement statistic this returns reflects that.
    """
    cells = _cells_of(terrain, area)
    if not cells:
        return DozerPass()

    if target_z is None:
        target_z = sum(terrain.z[c] for c in cells) / len(cells)

    # ONLY PLACED MATERIAL CAN BE PUSHED. A dozer spreads the stockpile, it does not excavate the
    # ground the stockpile sits on. Selecting high cells by elevation alone is correct on a flat pad
    # and catastrophic on any of the four sloping fill types: on a sidehill the high ground IS the
    # hill, and the blade drove a cell 4.43 m below the original surface, which is excavation nobody
    # performed and which broke the ledger against the terrain.
    highs = sorted(
        (c for c in cells if terrain.z[c] > target_z + tolerance_m and terrain.thickness(c) > tolerance_m),
        key=lambda c: -terrain.z[c],
    )
    if not highs:
        return DozerPass()

    area_m2 = terrain.cell_m * terrain.cell_m
    transfers: list[tuple[int, int, float]] = []

    # THE DOZER RELAYS. An earlier version only pushed from cells above the target directly onto cells
    # below it, and it stalled: after one pass the remaining high ground sat on one edge and the
    # remaining hollows on the other, 52 m apart against a 40 m push limit, with everything between
    # them already at target and therefore not a valid receiver. A real dozer moves material that far
    # by shoving it repeatedly, each shove within its own working distance. So a push here goes to the
    # LOWEST cell in reach that is simply lower than the source, whether or not that cell is below the
    # global target. Successive passes then walk material across the area.
    #
    # Transfers are capped at half the height difference, so a push can never invert a pair. That cap
    # is also what makes convergence provable: every transfer strictly reduces the sum of squared
    # elevations, which is bounded below.
    for c in highs:
        excess_m = terrain.z[c] - target_z
        if excess_m <= tolerance_m:
            continue
        # Capped by what is actually there: a cell cannot shed ground it never received.
        budget = min(excess_m * area_m2, blade_m3, terrain.thickness(c) * area_m2)
        if budget <= 0:
            continue
        cx, cy = terrain.xy(c)

        reach: list[tuple[float, int]] = []
        for d in cells:
            if d == c:
                continue
            dx_, dy_ = terrain.xy(d)
            if math.hypot(dx_ - cx, dy_ - cy) > push_m:
                continue
            reach.append((terrain.z[d], d))
        reach.sort()   # lowest ground first: that is where a blade pushes

        for _zd, d in reach:
            if budget <= 0:
                break
            diff = terrain.z[c] - terrain.z[d]
            if diff <= tolerance_m:
                break   # sorted ascending, so nothing further down the list is lower either
            take = min(budget, 0.5 * diff * area_m2)
            if take <= 0:
                continue
            terrain.z[c] -= take / area_m2
            terrain.z[d] += take / area_m2
            budget -= take
            transfers.append((c, d, take))

    return _finalise(terrain, transfers)


def push_to_crest(
    terrain: Terrain,
    area: Area,
    *,
    normal: tuple[float, float],
    depth_m: float = 0.3,
    push_m: float = DEFAULT_PUSH_M,
) -> DozerPass:
    """Shave material off the working floor and push it out over the face.

    This is the "dozed up the pile" operation: after a couple of paddock rows the accumulated heaps
    are pushed forward, which both advances the crest and clears the floor. ``depth_m`` is how much is
    taken off the surface in one pass, and ``normal`` is the direction of the face.

    Material that would leave the area is deposited at the last cell inside it rather than being
    dropped. A dozer does not lose material off the pad, and silently discarding it would break mass
    conservation in a way that is very hard to see afterwards.
    """
    cells = _cells_of(terrain, area)
    if not cells:
        return DozerPass()
    nx_, ny_ = normal
    mag = math.hypot(nx_, ny_)
    if mag < 1e-12:
        return DozerPass()
    nx_, ny_ = nx_ / mag, ny_ / mag

    area_m2 = terrain.cell_m * terrain.cell_m
    transfers: list[tuple[int, int, float]] = []
    # Work from the downstream edge backwards, so material pushed forward is not picked up again by
    # the same pass. Sorting by the along-normal coordinate does that.
    ordered = sorted(cells, key=lambda c: -(terrain.xy(c)[0] * nx_ + terrain.xy(c)[1] * ny_))

    for c in ordered:
        if terrain.thickness(c) <= depth_m:
            continue
        cx, cy = terrain.xy(c)
        tx, ty = cx + nx_ * push_m, cy + ny_ * push_m
        d = terrain.cell_at(tx, ty)
        if d is None or d == c:
            continue
        # Keep the destination inside the working area; a dozer works its own ground.
        if not area.contains(*terrain.xy(d)):
            continue
        vol = depth_m * area_m2
        terrain.z[c] -= depth_m
        terrain.z[d] += depth_m
        transfers.append((c, d, vol))

    return _finalise(terrain, transfers)


def build_berm(
    terrain: Terrain,
    crest: list[int],
    *,
    height_m: float = 1.5,
    source_depth_m: float = 0.2,
    gap_every: int = 8,
    gap_cells: int = 3,
) -> DozerPass:
    """Raise a safety berm along the crest, taking the material from just behind it.

    Berms are part of what dozers maintain during the edge campaign, and they are not decoration: the
    berm is what stops a reversing truck going over the edge, and it is why a tip head is kept sloped
    back from the void. Modelled as a mass-conserving transfer from the cells behind the crest onto
    the crest itself, so the berm costs material rather than appearing from nowhere.

    A BERM HAS GAPS IN IT, and leaving them out was a measured defect. A continuous berm along every
    crest cell walls the working area off from itself: refusals went UP as the dozer ran more often,
    62 percent at a pass per 10 loads against 33 percent at a pass per 40, because each pass added
    more unbroken wall. Real tip heads have breaks so equipment can pass through and so a grader can
    get to the face. ``gap_every`` and ``gap_cells`` set that pattern; setting ``gap_cells`` to zero
    restores the continuous berm and reproduces the defect, which is why it is a parameter rather
    than a constant.
    """
    if not crest:
        return DozerPass()
    area_m2 = terrain.cell_m * terrain.cell_m
    transfers: list[tuple[int, int, float]] = []
    crest_set = set(crest)

    period = max(1, gap_every + max(0, gap_cells))
    for pos, c in enumerate(crest):
        # Leave a break in the wall every ``gap_every`` cells, wide enough to drive through.
        if gap_cells > 0 and (pos % period) >= gap_every:
            continue
        need = height_m
        # Take from uphill neighbours that are not themselves crest cells.
        for n in terrain.neighbours(c):
            if need <= 0:
                break
            if n in crest_set or terrain.thickness(n) <= source_depth_m:
                continue
            take_m = min(source_depth_m, need)
            terrain.z[n] -= take_m
            terrain.z[c] += take_m
            transfers.append((n, c, take_m * area_m2))
            need -= take_m

    return _finalise(terrain, transfers)


def _reach(terrain, pool, cx: float, cy: float, floor_z: float, tol: float):
    """Candidate donors with their distance, nearest first once sorted."""
    for d in pool:
        if terrain.thickness(d) <= tol or terrain.z[d] <= floor_z:
            continue
        dx_, dy_ = terrain.xy(d)
        yield math.hypot(dx_ - cx, dy_ - cy), d


def build_ramp(
    terrain: Terrain,
    area: Area,
    *,
    max_grade: float,
    push_m: float = DEFAULT_PUSH_M,
    tolerance_m: float = 0.15,
    grade_frac: float = 0.85,
) -> DozerPass:
    """Cut and fill the access corridor into a drivable RAMP up onto the current working level.

    THE RAMP IS A CUT IN THE FILL, NOT A VOID RESERVED IN IT, and that distinction is the whole
    mechanic. Dump design is explicit that access to successive lifts is achieved by ESTABLISHING
    RAMPS of a suitable width and gradient, and that establishing is work the dozer does.

    The first design reserved the corridor in plan and kept every tip off it. That reads as sensible
    and it cannot work: a corridor 25 m wide and 58 m long that has to rise to the working level needs
    as much material as a sizeable fraction of the lift itself, all of it shoved in sideways by a
    blade with a fifteen-metre reach, while the trucks that could have supplied it are forbidden from
    driving there. Measured on a 90 m area: the entire 1296-cell area came out unreachable at a peak
    of 3.2 m, because the corridor stayed a trench with 3 m walls on both sides and there was no way
    up out of it.

    So the trucks fill the whole area, corridor included, and the dozer cuts the road back into what
    they filled, every pass. The material is then always right where the blade needs it.

    Measured before any of this existed: on a 70 m area with an 18 m bench, 69.8 percent of planned
    tips were refused and the pile stalled at 9.6 m, because nothing could drive onto what had been
    built.

    HOW IT IS BUILT. The corridor is graded from the access point up to the level of the material at
    its inner end, at no more than ``max_grade``. Material is taken from the nearest cells that stand
    ABOVE the target profile, so the ramp is cut and filled out of the pile rather than conjured:
    mass is conserved exactly, and a ramp that cannot be supplied comes out partial rather than
    fabricated.

    IT CUTS AS WELL AS FILLS, and that is what makes it work at all. Reserving the corridor in the
    plan does not keep it clear: a dump placed beside it spreads, and the spill stands wherever it
    lands. The first version only raised cells that were BELOW the target profile, so a corridor
    buried to two metres right at its mouth was left with a single-cell step of 0.63 grade against a
    truck limit of 0.50, and the flood fill could not get onto the ramp from the pad. Every cell of
    the corridor was individually passable and the area was unreachable: 92.7 percent of tips refused
    and the pile stalled at 4.07 m. A dozer grading a ramp blades the high spots down and shoves them
    into the low ones. So does this, and the cut supplies the fill before any of the pile is touched.
    """
    cells = _cells_of(terrain, area)
    if not cells:
        return DozerPass()

    ax, ay = area.access
    cx, cy = area.ramp_far
    vx, vy = cx - ax, cy - ay
    span = math.hypot(vx, vy)
    if span < 1e-9:
        return DozerPass()
    vx, vy = vx / span, vy / span

    ramp = [c for c in cells if area.on_ramp(*terrain.xy(c))]
    if not ramp:
        return DozerPass()

    # The top of the ramp is whatever the pile stands at where the corridor meets the working area.
    inner = [c for c in cells if not area.on_ramp(*terrain.xy(c)) and terrain.has_material(c)]
    if not inner:
        return DozerPass()
    top = sorted(terrain.z[c] for c in inner)[int(len(inner) * 0.6)]

    area_m2 = terrain.cell_m * terrain.cell_m
    transfers: list[tuple[int, int, float]] = []

    # Target profile: rise from the ground at the access end to `top`, never steeper than the limit.
    need: list[tuple[int, float]] = []
    for c in ramp:
        x, y = terrain.xy(c)
        along = (x - ax) * vx + (y - ay) * vy
        if along < 0:
            continue
        want = min(terrain.z0[c] + along * max_grade * grade_frac, top)
        if want - terrain.z[c] > tolerance_m:
            need.append((c, want - terrain.z[c]))

    # NO EARLY RETURN ON AN EMPTY `need`. That is the common case and it is the case that matters: a
    # corridor buried level with the platform has nothing BELOW the target profile, only material
    # above it, so bailing here meant the ramp was never cut and the whole area stayed walled off.
    # Measured on a clean 3 m platform: build_ramp returned zero transfers and the area went from
    # 0 of 1296 cells reachable to 0 of 1296.

    ramp_set = set(ramp)
    pool = [c for c in cells if c not in ramp_set]

    # THE CUT, FIRST. Corridor cells standing above the target profile are bladed down to it, never
    # below the original ground, and what comes off is the first material offered to the cells that
    # are short. This is what turns a buried corridor back into a ramp.
    #
    # EVERY MOVEMENT IS A RECORDED TRANSFER. The blade moves mass, and the lot ledger has to follow it
    # cell by cell; a scalar "spoil" bucket would balance the terrain and silently desynchronise the
    # provenance record that the whole product rests on.
    cut: list[list] = []
    for c in ramp:
        x, y = terrain.xy(c)
        along = (x - ax) * vx + (y - ay) * vy
        if along < 0:
            continue
        want = min(terrain.z0[c] + along * max_grade * grade_frac, top)
        excess = terrain.z[c] - max(want, terrain.z0[c])
        if excess > tolerance_m:
            cut.append([c, min(excess, terrain.thickness(c))])

    # The cut supplies the fill before any of the pile is touched. Cells needing most go first, so
    # the deepest part of the trench closes rather than every cell getting a smear.
    for c, deficit in sorted(need, key=lambda t: -t[1]):
        remaining = deficit
        for entry in cut:
            if remaining <= tolerance_m:
                break
            d, avail = entry
            if avail <= tolerance_m:
                continue
            take = min(remaining, avail)
            terrain.z[d] -= take
            terrain.z[c] += take
            transfers.append((d, c, take * area_m2))
            entry[1] = avail - take
            remaining -= take

    # Whatever the corridor still has to shed is shoved sideways onto the nearest cell of the working
    # area, which is where a blade actually puts it. The relaxation that follows the pass spreads it.
    for d, avail in cut:
        if avail <= tolerance_m or not pool:
            continue
        dx_, dy_ = terrain.xy(d)

        def _dist(q: int, _x: float = dx_, _y: float = dy_) -> float:
            qx, qy = terrain.xy(q)
            return math.hypot(qx - _x, qy - _y)

        sink = min(pool, key=_dist)
        terrain.z[d] -= avail
        terrain.z[sink] += avail
        transfers.append((d, sink, avail * area_m2))

    # Whatever the cut could not cover is re-measured against the profile the corridor now has, and
    # made up out of the pile beside it.
    need = []
    for c in ramp:
        x, y = terrain.xy(c)
        along = (x - ax) * vx + (y - ay) * vy
        if along < 0:
            continue
        want = min(terrain.z0[c] + along * max_grade * grade_frac, top)
        if want - terrain.z[c] > tolerance_m:
            need.append((c, want - terrain.z[c]))

    for c, deficit in need:
        remaining = deficit
        cxm, cym = terrain.xy(c)
        near = sorted(
            _reach(terrain, pool, cxm, cym, terrain.z[c], tolerance_m),
            key=lambda t: t[0],
        )
        for dist, d in near:
            if remaining <= tolerance_m:
                break
            if dist > push_m:
                break
            # Never take so much that the donor drops below the cell it is feeding: that would dig a
            # new hole beside the ramp instead of grading it.
            avail = min(terrain.thickness(d), max(0.0, terrain.z[d] - terrain.z[c]) * 0.5)
            take = min(remaining, avail)
            if take <= tolerance_m:
                continue
            terrain.z[d] -= take
            terrain.z[c] += take
            transfers.append((d, c, take * area_m2))
            remaining -= take

    return _finalise(terrain, transfers)
