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
from dataclasses import dataclass, field, replace
from enum import Enum

from .blocks import BlockModel, Parcel, transfer_distances
from .relax import relax_to
from .terrain import Terrain
from .truck import NoRoute, Route, passable_mask, reachable_mask, solve_route


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
    # THE SIZE OF THE FEED, which is what makes the segregation half of this engine mean anything
    # operationally. Coarse runs to the toe of a dumped face; a campaign that cuts the toe therefore
    # delivers coarse feed and one that cuts the crest delivers fines, and until this field existed
    # the engine modelled the sorting in detail and then threw the answer away at the moment it
    # became a plant-facing number. Tonnage-weighted over the parcels the cut removed.
    coarse_fraction: float = 0.0
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
    # The unsimplified grid paths behind those two polylines. The polyline is what gets drawn and
    # what the artifact carries; the cells are what the per-step gradient rule can actually be
    # checked against, since `step_ok` divides by ONE cell width and a simplified segment can span
    # twenty. Keeping both is what makes "every step of this route is drivable" a testable claim
    # rather than one that happens to hold whenever the long segments are flat.
    approach_cells: list[int] = field(default_factory=list)
    departure_cells: list[int] = field(default_factory=list)
    # Where the loader itself sits: on the cut, which is what the centroid of the engaged cells is.
    loader: tuple[float, float] | None = None


@dataclass(frozen=True)
class LoaderSpec:
    """The machine at the face, and the geometry that bounds what one cut can touch.

    THE ENGINE HAD NO MACHINE. A cut was a tonnage taken from a slab, and the slab was the whole
    working face: ``depth_m`` deep by ``width_m`` across, every cell of it engaged on every cut no
    matter how little material the cut removed. Measured on the shipped artifacts that came to a mean
    footprint of 594 square metres per cut across 632 cuts, and the worst case was the entire slab,
    900 square metres. One scenario took 355 tonnes while touching 486 square metres, which is a seven
    centimetre skim off half a football pitch rather than anything a loader does. The symptom that
    gives it away without any geometry at all is the provenance: a single 881 tonne cut reported
    material from 108 distinct dig blocks. Fifteen bucket passes cannot sample 108 dig blocks.

    So the machine is explicit now, and the two numbers that matter are the ones that bound a cut:

      ``dig_radius_m``      how far the machine works from one stance before it has to tram along the
                            face. A cut cannot touch a cell outside this radius, whatever the tonnage.
      ``max_cut_height_m``  how high a face it can safely cut in one pass, which with the face's own
                            ``max_face_m`` limit is what stops a cut taking a column top to bottom.

    WHAT IS CLAIMED. These defaults are the working envelope of the large hydraulic front shovel class
    used on a pre-crusher stockpile, and they are a PARAMETER of the run, declared and adjustable, not
    a measured fit to a particular machine. The result that does not depend on the exact figure is the
    one the previous model got wrong: the footprint of a cut scales with the tonnage removed and is
    bounded by the reach of the machine, instead of being the whole face every time.
    """

    name: str = "hydraulic front shovel, 60 t payload class"
    # Nominal bucket and payload, carried for reporting: the cut is sized in tonnes by the caller.
    bucket_m3: float = 34.0
    payload_t: float = 60.0
    # The working envelope. These two bound the footprint.
    dig_radius_m: float = 15.0
    max_cut_height_m: float = 15.0

    def passes_for(self, load_t: float, bulk_density_t_m3: float) -> float:
        """Bucket passes to fill a load of ``load_t``, the ratio an operator quotes for a pairing.

        A pass count is tonnes wanted over tonnes per bucket, and tonnes per bucket needs the
        material's density: a bucket is a VOLUME. The previous version divided the machine's own
        payload by its own bucket volume and returned 1.76, which is tonnes per cubic metre, a
        density, not a count of anything. It read plausibly because a number near two is also a
        plausible pass count, which is the kind of unit error a name hides rather than reveals.
        """
        per_bucket = self.bucket_m3 * max(bulk_density_t_m3, 1e-9)
        return max(load_t, 0.0) / max(per_bucket, 1e-9)


@dataclass
class ReclaimFace:
    """The working face: where the machine is, how deep it cuts, and how high a face it will stand.

    ``max_face_m`` is a safety limit on the height of the face being worked, and it is the reason
    reclaim cannot simply take a column from top to bottom in one pass.

    ``position_m`` is how far the face has advanced INTO the pile and ``offset_m`` is where the machine
    is standing ACROSS it. The second one is new and it is the fix for a cut being the size of the
    whole face: a loader works a stretch of face it can reach, then trams along to the next stretch,
    and only when it has worked the whole width does the face advance a cut deeper. Both are stepped
    by ``step``.
    """

    method: ReclaimMethod = ReclaimMethod.FULL_HEIGHT
    # Position of the face along its advance direction, in metres from the pad origin.
    position_m: float = 0.0
    # Direction the face advances, as a unit vector in pad coordinates.
    direction: tuple[float, float] = (1.0, 0.0)
    # How far into the pile one cut reaches.
    depth_m: float = 5.0
    # Across-face extent of the FACE. Not of one cut: see ``LoaderSpec.dig_radius_m`` for that.
    width_m: float = 30.0
    # Safe working face height.
    max_face_m: float = 15.0
    # The machine working it.
    loader: LoaderSpec = field(default_factory=LoaderSpec)
    # Where the machine stands across the face, in metres from the near edge of the width window.
    offset_m: float = 0.0
    # Where the across-face window is CENTRED, as a coordinate along the across-face axis. Defaults to
    # the middle of the pad, which is only right when the pile is pad-centred: a yard tiles several
    # areas and each face belongs to one of them, so the caller that knows the area passes its centre.
    centre_t_m: float | None = None
    # Where the face started, kept so it can go back. See `rewind`.
    origin_m: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.origin_m = self.position_m

    def rewind(self) -> None:
        """Put the face back at its starting position, at the near edge of the width.

        A CONCURRENT CAMPAIGN RECLAIMS A PILE THAT IS STILL BEING BUILT, so a face that has worked its
        way past the end of the material is not finished, it is merely ahead of the trucks. Leaving it
        parked out there means every later cut finds nothing and the campaign silently stops: measured,
        the concurrent scenario fell from 28 cuts to 2 and the surge scenario from 74 to 2, both of them
        still delivering a plausible-looking feed series from the handful that got through.
        """
        self.position_m = self.origin_m
        self.offset_m = 0.0

    def _basis(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """The along-face and across-face unit vectors, or None if the direction is degenerate."""
        dx, dy = self.direction
        mag = math.hypot(dx, dy)
        if mag < 1e-12:
            return None
        dx, dy = dx / mag, dy / mag
        return (dx, dy), (-dy, dx)

    def _centre_t(self, terrain: Terrain, across: tuple[float, float]) -> float:
        if self.centre_t_m is not None:
            return self.centre_t_m
        px, py = across
        cx = terrain.nx * terrain.cell_m / 2.0
        cy = terrain.ny * terrain.cell_m / 2.0
        return cx * px + cy * py

    def engaged_cells(self, terrain: Terrain) -> list[int]:
        """The ENVELOPE: cells within ``depth_m`` ahead of the face and ``width_m`` across it.

        This is the ground the face covers, which is what the machine may work its way along. It is
        NOT the footprint of one cut, and treating it as one is the defect this class now documents in
        ``LoaderSpec``. For the cells a given cut actually digs, call ``bite``.
        """
        basis = self._basis()
        if basis is None:
            return []
        (dx, dy), (px, py) = basis
        centre_t = self._centre_t(terrain, (px, py))

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

    def _occupied(
        self, terrain: Terrain, envelope: list[int] | None = None
    ) -> tuple[float, float, float] | None:
        """``(s_near, t_lo, t_hi)`` of the material actually standing in front of the face.

        The stance is taken from where the MATERIAL is rather than from the nominal ``width_m``
        window, because the window is a bound and not a description: a caller that does not want an
        across-face limit passes a width wider than the pad, and deriving the machine's position from
        that puts it off the edge of the world. Where the pile is, is where the machine stands.
        """
        basis = self._basis()
        if basis is None:
            return None
        (dx, dy), (px, py) = basis
        s_near = t_lo = t_hi = None
        for c in (self.engaged_cells(terrain) if envelope is None else envelope):
            x, y = terrain.xy(c)
            s = x * dx + y * dy
            t = x * px + y * py
            s_near = s if s_near is None else min(s_near, s)
            t_lo = t if t_lo is None else min(t_lo, t)
            t_hi = t if t_hi is None else max(t_hi, t)
        if s_near is None:
            return None
        return s_near, t_lo, t_hi  # type: ignore[return-value]

    def stance(self, terrain: Terrain, envelope: list[int] | None = None) -> tuple[float, float]:
        """Where the machine stands to work the current cut, in pad metres.

        At the near edge of the material along the advance direction, which is where a face IS, and
        at ``offset_m`` across it. The stretch it can reach from here is one dig radius either side,
        so the stance sits a radius in from the near edge of the stretch rather than on the edge of
        it. A face whose material is narrower than the machine's reach puts it in the middle, which
        is what an operator does with a short pile.
        """
        basis = self._basis()
        if basis is None:
            return 0.0, 0.0
        (dx, dy), (px, py) = basis
        occ = self._occupied(terrain, envelope)
        if occ is None:
            # Nothing in front of the face. The stance is still defined so callers do not have to
            # special-case it, and `bite` correctly returns nothing from it.
            centre_t = self._centre_t(terrain, (px, py))
            s = self.position_m
            return s * dx + centre_t * px, s * dy + centre_t * py
        s_near, t_lo, t_hi = occ
        r = self.loader.dig_radius_m
        span = t_hi - t_lo
        if span <= 2.0 * r:
            t = 0.5 * (t_lo + t_hi)
        else:
            t = t_lo + min(self.offset_m + r, span - r)
        return s_near * dx + t * px, s_near * dy + t * py

    def bite(
        self, terrain: Terrain, model: BlockModel, tonnes_wanted: float
    ) -> list[tuple[int, float]]:
        """The cells this cut actually digs, nearest the machine first, and how deep into each.

        THE FOOTPRINT SCALES WITH THE TONNAGE, which is the whole point. The machine works the cell in
        front of it down to a full bench lift, then the next, until it has the tonnage asked for; a
        small cut leaves a small hole. The last cell is partial, taking only the remainder.

        Two things bound it, and both are the machine rather than the plan:

          * no cell outside ``dig_radius_m`` of the stance is a candidate, so a cut cannot reach across
            a pile it would have to tram to;
          * no cell gives up more than one lift, ``min(max_face_m, max_cut_height_m)``, so a cut cannot
            take a fifty metre column in one pass.

        If the reachable ground cannot supply the tonnage the cut takes what is there and reports the
        shortfall by simply being smaller, which is the honest answer: the machine has to tram.
        """
        if tonnes_wanted <= 0:
            return []
        # ONE grid scan for the whole attempt. `bite`, `stance` and `step` each used to walk every cell
        # of the pad independently, and `next_cut` calls all three per stance while it assembles a cut,
        # so a wide yard spent four full scans per attempt and the heavy scenarios stopped finishing.
        envelope = self.engaged_cells(terrain)
        sx, sy = self.stance(terrain, envelope)
        lift = min(self.max_face_m, self.loader.max_cut_height_m)
        r2 = self.loader.dig_radius_m ** 2
        per_m = model.cell_area_m2 * model.bulk_density_t_m3
        if per_m <= 0 or lift <= 0:
            return []

        # DEEPEST FIRST, NEAREST TO BREAK THE TIE. A machine works the FACE, which is where the
        # material stands; it does not skim the thin apron in front of it because that happens to be
        # closer. Ordering purely by distance made a cut on a pile with a shallow near edge spread
        # outward instead of digging in: measured on the concurrent scenario, a 3000 tonne cut took
        # 1035 square metres at a mean depth of 1.45 m, which is a skim over a third of an acre rather
        # than a shovel working a face. Taking the deep ground first concentrates the same tonnage into
        # the standing material, which is both what an operator does and a far smaller hole.
        #
        # The depth is capped at one lift before sorting, so every cell with a full lift standing on it
        # ties and the distance decides between them. That is the face, worked nearest first.
        near: list[tuple[float, float, int]] = []
        for c in envelope:
            x, y = terrain.xy(c)
            d2 = (x - sx) ** 2 + (y - sy) ** 2
            if d2 > r2:
                continue
            depth = min(model.thickness(c), lift)
            if depth <= 1e-9:
                continue
            near.append((-depth, d2, c))
        # Index is the last tiebreak via the tuple order, so a run is reproducible rather than
        # dependent on the order the envelope happened to come out in.
        near.sort()

        out: list[tuple[int, float]] = []
        got = 0.0
        for neg_depth, _d2, c in near:
            if got >= tonnes_wanted - 1e-9:
                break
            depth = -neg_depth
            t = depth * per_m
            if got + t > tonnes_wanted:
                depth = (tonnes_wanted - got) / per_m
                t = tonnes_wanted - got
            out.append((c, depth))
            got += t
        return out

    def step(self, terrain: Terrain, envelope: list[int] | None = None) -> bool:
        """Move the machine to its next stance, and the face deeper when the width is swept.

        A loader trams along the face by the stretch it just worked, which is two dig radii. When it
        runs off the end of the material it goes back to the near edge and the face advances one cut
        deeper. Returns whether there is anything left ahead, same contract as ``advance``.
        """
        occ = self._occupied(terrain, envelope)
        self.offset_m += 2.0 * self.loader.dig_radius_m
        if occ is not None and self.offset_m + self.loader.dig_radius_m < (occ[2] - occ[1]):
            return True
        self.offset_m = 0.0
        return advance(self, terrain)


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

    THE FOOTPRINT IS THE MACHINE'S, NOT THE FACE'S. This used to spread the cut proportionally over
    every cell of the working face, so a small cut was a thin skim over a very large area: see
    ``LoaderSpec`` for the measured consequence. It now digs the cells within reach of the machine's
    stance, nearest first, one bench lift at a time, until it has the tonnage. ``Cut.cells`` is
    therefore the ground actually dug and it grows and shrinks with the tonnage taken.
    """
    if tonnes_wanted <= 0:
        return Cut(0.0, 0.0)

    bite = face.bite(terrain, model, tonnes_wanted)
    if not bite:
        return Cut(0.0, 0.0)

    per_m = model.cell_area_m2 * model.bulk_density_t_m3   # tonnes per metre of column

    grade_num = 0.0
    disp_num = 0.0
    unc_num = 0.0
    coarse_num = 0.0
    prov: dict[int, float] = {}
    got = 0.0
    touched: list[int] = []

    for c, want_m in bite:
        col = model.columns[c]
        if not col:
            continue
        if want_m <= 0:
            continue
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
            coarse_num += t * p.coarse_fraction
            prov[p.source_block] = prov.get(p.source_block, 0.0) + t
        terrain.z[c] -= sum(p.thickness_m for p in taken)

    if got <= 0:
        return Cut(0.0, 0.0)

    # Undercutting leaves the surrounding material unsupported; take it down to repose. The ledger
    # must be carried along with it: relaxation MOVES MATERIAL, and a ledger that is not told about
    # the movement drifts away from the terrain, so every grade reported afterwards is attached to
    # the wrong place. Doing it here rather than leaving it to the caller is deliberate, because
    # forgetting exactly this is what the previous engine did.
    # SEEDED ON THE CELLS THE CUT ACTUALLY TOUCHED, which is what the build side has always done with
    # `settle(active=...)`. This called the unseeded form and relaxed the whole pad on every cut.
    #
    # Measured before claiming anything for it: seeding changes the RESULT not at all, 768 against 767
    # square metres of surface moved per cut on the reference scenario, because a pile that was stable
    # before the cut has nothing to relax anywhere except around the cut. So this is a matter of the
    # work following the machine rather than a fix for a visible defect, and correctness is unaffected
    # either way: `relax_to` sweeps the whole pad regardless if anything is left over the angle.
    #
    # And the surface that moves is legitimately larger than the bite. Undercutting 4.5 m into ground
    # standing at 37 degrees pulls material in from about 6 m around, so a 336 square metre bite shows
    # up as roughly 770 of surface change. That apron is the slump, it is the physics, and it is not
    # the machine reaching further than it can.
    moves = relax_to(terrain, repose_deg, active=set(touched))
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
        coarse_fraction=coarse_num / got,
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
                # `replace`, never a positional rebuild. A rebuild that names the fields silently
                # drops any field added later, and that is not hypothetical: it is exactly how
                # `coarse_fraction` came to be zeroed on every split parcel in `blocks.py`, which put
                # a 40 percent deficit into a shipped release with every gate green.
                out.append(replace(p, z1_m=cut_z))
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
        out.append(replace(p, z0_m=p.z0_m, z1_m=p.z0_m + t))
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


# A backstop on the search for the next workable stance. The search terminates on its own when the
# face runs off the end of the pile, since ``advance`` says so; this only stops a pathological
# geometry from spinning, and it is generous enough never to bind on a real pad.
MAX_STANCES_TRIED = 4096


def next_cut(
    terrain: Terrain,
    model: BlockModel,
    face: ReclaimFace,
    tonnes_wanted: float,
    *,
    repose_deg: float,
) -> Cut | None:
    """Assemble the next ``tonnes_wanted`` of feed, tramming the machine as far as it takes.

    A CUT IS A QUANTITY OF FEED, NOT A SINGLE BUCKET FROM A SINGLE SPOT. The reach of the machine
    bounds what it can take from ONE stance, and that bound is the whole point of ``bite``; it must
    not also bound the parcel the plant asked for. A face whose stance holds ninety tonnes does not
    turn a nine hundred tonne cut into a ninety tonne one, it makes the machine tram and keep loading,
    which is what tramming is for. Getting this wrong is visible immediately in the tonnage: the first
    version of this function returned the first non-empty stance and cut the delivered feed to a
    quarter of what the campaign asked for, leaving most of the pile standing.

    So it takes from the current stance, and while there is still tonnage owed it moves the machine
    and takes again, merging everything into one cut. The footprint still scales with the tonnage,
    because every cell in it was dug for the material in it.

    Returns None when the pile in front of the face is worked out, which ends the campaign.
    """
    parts: list[Cut] = []
    owed = tonnes_wanted
    rewound = False

    # HOW FAR THE MACHINE WILL TRAM FOR ONE PARCEL. A loader filling a cut works a stretch of face,
    # not the whole yard, and if that stretch cannot supply the tonnage then the parcel is SHORT. That
    # is a real operational answer and the honest one: a pile 0.3 m thick cannot deliver 3000 tonnes,
    # and a model that says otherwise is sweeping ground to hide it. Unbounded assembly did exactly
    # that on the concurrent scenarios, where the reclaim runs while the pile is still being built:
    # `surge` came out at 3303 square metres per cut removing 0.31 m, a skim across most of the pad.
    #
    # One sweep of the width, which is the stretch reachable without abandoning the face.
    sweep = max(2, math.ceil(face.width_m / (2.0 * face.loader.dig_radius_m)))
    trammed = 0

    for _ in range(MAX_STANCES_TRIED):
        if owed <= 1e-9:
            break
        c = cut(terrain, model, face, owed, repose_deg=repose_deg)
        if c.tonnes > 0:
            parts.append(c)
            owed -= c.tonnes
            # Worked out at this stance if it could not fill the order from here.
            if owed <= 1e-9:
                break
        if parts:
            # Only counted once the machine is actually loading. Getting TO the first productive
            # stance is searching, not tramming, and a face whose near ground is worked out must
            # still be allowed to find the material.
            if trammed >= sweep:
                break
            trammed += 1
        if not face.step(terrain):
            # The face has run past the end of the material. On a CONCURRENT campaign that does not
            # mean the pile is finished, only that the reclaim is ahead of the trucks, so the face
            # goes back to its start and works forward again over ground that has since been built
            # on. Once per call: a second run-off with nothing found means there really is nothing.
            if rewound:
                break
            face.rewind()
            rewound = True
    if not parts:
        return None
    return _merge(parts)


def _merge(parts: list[Cut]) -> Cut:
    """Combine the loads taken from several stances into the one parcel of feed they make up.

    Everything intensive is tonnage-weighted, which is the only correct weighting for a quantity that
    will be averaged against other cuts downstream, and the provenance fractions are recombined on the
    same basis so they still sum to one. The haulage fields are left unset here: the caller routes the
    truck once, for the assembled cut, on the surface all of it left behind.
    """
    if len(parts) == 1:
        return parts[0]
    total = sum(p.tonnes for p in parts)
    if total <= 0:
        return parts[0]
    prov: dict[int, float] = {}
    for p in parts:
        for block, share in p.provenance.items():
            prov[block] = prov.get(block, 0.0) + share * p.tonnes
    cells: list[int] = []
    seen: set[int] = set()
    for p in parts:
        for c in p.cells:
            if c not in seen:
                seen.add(c)
                cells.append(c)

    def wmean(attr: str) -> float:
        return sum(getattr(p, attr) * p.tonnes for p in parts) / total

    return Cut(
        tonnes=total,
        grade=wmean("grade"),
        provenance={k: v / total for k, v in prov.items()},
        displacement_m=wmean("displacement_m"),
        grade_uncertainty=wmean("grade_uncertainty"),
        cells=cells,
        coarse_fraction=wmean("coarse_fraction"),
    )



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


@dataclass(frozen=True)
class HaulCycle:
    """Where the truck stood for one cut, and the two routes it drove.

    A record rather than a tuple because it carries five things now: the two legs each come with the
    grid path behind their polyline, and positional unpacking of five values at two call sites is how
    a caller ends up silently assigning the departure to the approach.

    ``stand`` is None when the cut cannot be served at all.
    """

    stand: tuple[float, float] | None
    loader: tuple[float, float] | None
    approach: Route | None = None
    departure: Route | None = None

    def apply_to(self, c: Cut) -> None:
        """Write the cycle onto the cut it belongs to, polylines and grid paths together."""
        c.stand, c.loader = self.stand, self.loader
        c.approach = list(self.approach.points) if self.approach else []
        c.departure = list(self.departure.points) if self.departure else []
        c.approach_cells = list(self.approach.cells) if self.approach else []
        c.departure_cells = list(self.departure.cells) if self.departure else []


def haul_cycle(
    terrain: Terrain,
    cells: list[int],
    *,
    exit_xy: tuple[float, float],
    max_grade: float,
) -> HaulCycle:
    """Route an empty truck in to the cut and a loaded one back out.

    ``HaulCycle.stand`` is None when nothing drivable is within reach of the cut, which is a real
    refusal and is reported rather than hidden: a campaign that has undercut its own access cannot be
    served, and saying so is the point of modelling the haulage at all.

    The approach and the departure are solved SEPARATELY rather than one reversed, because the
    surface changes between them: the cut has just been taken and the face relaxed, so the way out is
    not always the way in.
    """
    loader = _centroid(terrain, cells)
    passable = passable_mask(terrain, max_grade)
    reach = reachable_mask(terrain, exit_xy, max_grade, passable=passable)

    # The nearest cell to the loader that a truck can actually stand on AND get to, EXCLUDING the
    # ground the loader is working.
    #
    # TWO MACHINES CANNOT OCCUPY ONE CELL, and this module exists partly because the previous engine
    # let them: the stacker and the reclaimer were measured inside the same cell in 5 of 51 cuts. The
    # exclusion was not needed while a cut spread over the whole face, because the centroid of a
    # 594 square metre skim was never a cell a truck would pick anyway. Once the bite became compact
    # the centroid landed on freshly levelled, perfectly drivable ground, and the nearest stand to the
    # loader became the loader's own cell: measured on `intensive_drain`, a separation of exactly
    # zero. A smaller footprint is the right answer and this is what it uncovered underneath.
    dug = set(cells)
    best: int | None = None
    best_d = float("inf")
    for c in range(terrain.n_cells):
        if c in dug or not (passable[c] and reach[c]):
            continue
        x, y = terrain.xy(c)
        d = (x - loader[0]) ** 2 + (y - loader[1]) ** 2
        if d < best_d:
            best_d = d
            best = c
    if best is None:
        return HaulCycle(stand=None, loader=loader)

    stand = terrain.xy(best)
    try:
        # `strict_goal`: the truck PARKS here to be loaded, it does not tip over an edge, so the
        # last step in has to be climbable like every other one.
        approach = solve_route(
            terrain, exit_xy, stand, max_grade=max_grade, passable=passable, strict_goal=True
        )
    except NoRoute:
        return HaulCycle(stand=None, loader=loader)
    try:
        departure = solve_route(
            terrain, stand, exit_xy, max_grade=max_grade, passable=passable, strict_goal=True
        )
    except NoRoute:
        # The way out is the way in, reversed, which is the only honest fallback: the surface has not
        # changed between the two solves, so if one direction routes and the other does not it is the
        # asymmetry of the gradient rule and not a different pile.
        departure = Route(list(reversed(approach.points)), cells=list(reversed(approach.cells)))
    return HaulCycle(stand=stand, loader=loader, approach=approach, departure=departure)

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
        c = next_cut(terrain, model, face, cut_tonnes, repose_deg=repose_deg)
        if c is None:
            break
        if haul:
            # Routed AFTER the cut, on the surface the cut left behind, because that is the ground
            # the truck actually drives on: the face has just moved and the material has relaxed.
            haul_cycle(
                terrain, c.cells, exit_xy=exit_xy, max_grade=max_grade
            ).apply_to(c)
        out.append(c)
    return out
