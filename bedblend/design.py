"""The dump plan: named areas, a bench schedule, and the tip positions that follow from them.

WHY A PLAN EXISTS. Trucks do not discharge at arbitrary coordinates. The operational record proves it:
a fleet-management dump event locates the load by the "name and bench height of dump location polygon"
(Young and Rogers, Minerals 2021, 11, 636, table 1). The area is named and predefined; the level is a
bench. Feeding points are a consequence of a plan, not a free choice, and the previous engine's
acceptance of any coordinate is the defect this module removes.

THE TWO PHASES, which are the specification for how a bench gets built. Quoted from the same paper,
section 3:

    "In a heaped fill stockpiling scenario, dumping occurs in two phases. The first phase is a series
    of paddock dumps to form the base layer of the stockpile. The second phase involves building an
    upper layer above an area of the paddock dumps from which a campaign of edge dumps occurs until
    the bench is completed."

So one bench is two campaigns with two different geometries:

  * PADDOCK, on flat ground: heaps on an evenly spaced row lattice. "the rows space evenly and
    maintain homogeneity along their respective row or column". An industrial simulation puts numbers
    on it: 50 loads dumped 3 m apart along a 150 m row, with the material dozed up the pile after two
    rows (Neufeld, Lyall and Deutsch, CCG Report 8 paper 306, 2006, for Anglo American).
  * EDGE, over a face: a seed cluster, then "radial progression from an initial cluster point", the
    crest advancing in "sweeping radial movements" until the campaign "fills the designed volume for
    the given bench".

WHAT THIS MODULE DOES NOT DO. It does not place material and it does not know about terrain. It emits
an ordered sequence of intended tip positions. Whether a given position can actually be reached is a
question for trafficability at execution time, and a position that cannot be reached is refused there
rather than being quietly removed here. Keeping the plan and its feasibility separate is what makes it
possible to show a reader the difference between what was planned and what the pile allowed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    """Which campaign a tip position belongs to. The value is the dump operator that will run."""

    PADDOCK = "paddock"
    EDGE = "edge"


@dataclass(frozen=True)
class TipPosition:
    """One intended discharge: where the truck stands, which way it faces, and under what plan.

    ``heading_rad`` is the direction the material is thrown, measured from the +x axis. For a paddock
    dump it is the truck's own orientation along its row. For an edge dump it is resolved against the
    live crest at execution time, because the correct direction is the outward normal of the face and
    the face has moved since the plan was written.
    """

    x_m: float
    y_m: float
    heading_rad: float
    phase: Phase
    area: str
    bench: int
    seq: int

    @property
    def heading_deg(self) -> float:
        return math.degrees(self.heading_rad)


@dataclass(frozen=True)
class Bench:
    """One lift of one area: how high it goes and how much material it is designed to hold.

    ``designed_volume_m3`` is what terminates the edge campaign. The paper's phrasing is that edge
    dumping continues "until it fills the designed volume for the given bench", so the stopping rule is
    a volume target, not a load count.
    """

    index: int
    top_m: float
    designed_volume_m3: float


@dataclass
class Area:
    """A named working region of the stockyard, and the schedule of benches to be built in it.

    THE AREA IS THE SECTOR. This is the object a load is routed to before it is placed, which is how
    sectors come to exist at all: an operation classifies each truckload from its ore-control estimate
    and sends it to a designated area, building one area per material class at a time (CCG 2006 routes
    by a silica-to-magnesia threshold of 1.75, with one high pile and one low pile under construction
    simultaneously). Aggregating the raw cells that belong to an area is the sector rollup.

    The footprint is an axis-aligned rectangle in pad metres. A general polygon is the honest
    representation of a real dump-location polygon and is a known simplification here; a rectangle is
    enough to carry a name, a schedule and a containment test, and the containment test is the only
    thing the rest of the engine asks of it.
    """

    name: str
    x0_m: float
    y0_m: float
    x1_m: float
    y1_m: float
    benches: list[Bench] = field(default_factory=list)
    # What this area is for, in the operation's own vocabulary: "high SMR", "low grade", "oxide".
    # Free text on purpose. The engine never branches on it; it is the label a reader reads.
    material_class: str = ""
    # WHERE EQUIPMENT ENTERS. Dump design reserves access: a footprint is built up by lifts, with
    # "access to successive dump lifts achieved by establishing ramps of a suitable width, super
    # elevation and gradient" (Cogent Engineering 4(1), 1387955). Without a reserved corridor the pile
    # grows over its own access and the plan starts asking for tips no truck can reach. Measured
    # before this existed: a third of all planned tips refused, 79 of 80 for having no drivable route.
    # Defaults to the area's own lower-left corner, which is where a yard laid out from the origin is
    # normally entered.
    access_xy: tuple[float, float] | None = None
    ramp_width_m: float = 25.0

    def __post_init__(self) -> None:
        if self.x1_m <= self.x0_m or self.y1_m <= self.y0_m:
            raise ValueError(f"area {self.name!r} has a non-positive extent")

    @property
    def width_m(self) -> float:
        return self.x1_m - self.x0_m

    @property
    def length_m(self) -> float:
        return self.y1_m - self.y0_m

    @property
    def plan_area_m2(self) -> float:
        return self.width_m * self.length_m

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x0_m + self.x1_m) / 2.0, (self.y0_m + self.y1_m) / 2.0

    def contains(self, x_m: float, y_m: float) -> bool:
        return self.x0_m <= x_m <= self.x1_m and self.y0_m <= y_m <= self.y1_m

    def inset(self, d_m: float) -> Area:
        """The same area shrunk by ``d_m`` on every side, keeping its access and ramp.

        THIS IS WHAT MAKES A BENCH A BENCH. Every lift sits inside the one below it by the horizontal
        run of the face, so the sides of the finished solid stand at the angle of repose. Filling
        every lift over the FULL footprint instead builds a slab with vertical sides that the
        material immediately slumps off: measured on a 90 m square designed to 26 m, the volume came
        out right and the peak was 14.6 m, because the loads were spread over 8100 square metres at
        every level instead of climbing a shrinking one.

        It clamps rather than inverting, so a caller can ask for more inset than the area has and get
        a degenerate area back to stop on.
        """
        cx, cy = self.centre
        hw = max((self.x1_m - self.x0_m) / 2.0 - d_m, 0.0)
        hl = max((self.y1_m - self.y0_m) / 2.0 - d_m, 0.0)
        return Area(
            name=self.name,
            x0_m=cx - hw, y0_m=cy - hl, x1_m=cx + hw, y1_m=cy + hl,
            material_class=self.material_class,
            access_xy=self.access_xy or self.access,
            ramp_width_m=self.ramp_width_m,
            benches=self.benches,
        )

    @property
    def access(self) -> tuple[float, float]:
        # THE DEFAULT IS THE MIDDLE OF THE +Y EDGE, not a corner. `rectangular_yard` lays areas out
        # along +x from the origin, so the (x0, y0) corner it used to default to is the one buried
        # deepest in the layout: for a single 90 m area on a 140 m pad it sat in the pad corner with
        # the area itself between it and every approach, and no truck could reach the entrance at
        # all. An edge midpoint on the open side is where a haul road actually meets a dump.
        return self.access_xy if self.access_xy is not None else ((self.x0_m + self.x1_m) / 2.0, self.y1_m)

    def on_ramp(self, x_m: float, y_m: float) -> bool:
        """Is this point inside the reserved access corridor.

        The corridor is the strip of the area within half a ramp width of the straight line from the
        access point ACROSS the area, not merely to its centre. The run available is what limits the
        lift a ramp can serve: at a working gradient of about 0.43 a corridor half the area long tops
        out around 19 m, and a bench schedule that designs past that produces a working level nothing
        can climb to. The full span roughly doubles it.
        """
        ax, ay = self.access
        fx, fy = self.ramp_far
        vx, vy = fx - ax, fy - ay
        span = math.hypot(vx, vy)
        if span < 1e-9:
            return False
        vx, vy = vx / span, vy / span
        dx, dy = x_m - ax, y_m - ay
        along = dx * vx + dy * vy
        if along < 0.0 or along > span:
            return False
        return abs(-dy * vx + dx * vy) <= self.ramp_width_m / 2.0

    @property
    def ramp_far(self) -> tuple[float, float]:
        """The inner end of the access corridor: the access point reflected through the centre."""
        cx, cy = self.centre
        ax, ay = self.access
        return (2.0 * cx - ax, 2.0 * cy - ay)

    def distance_from_access(self, x_m: float, y_m: float) -> float:
        ax, ay = self.access
        return math.hypot(x_m - ax, y_m - ay)


@dataclass
class DumpPlan:
    """The whole design: the areas, the order they are worked, and the rules that generate tips.

    ``row_spacing_m`` and ``tip_spacing_m`` are the paddock lattice. The CCG figures are 3 m between
    loads along a row; row separation is a site choice and defaults here to roughly two truck lengths
    so that adjacent rows do not merge before the dozer reaches them.

    ``loads_per_dozer_pass`` is the CCG rule made explicit: "The material is dozed up the pile after
    two rows have been dumped." Expressed in loads rather than rows so a caller can tighten or loosen
    it without restructuring the lattice.
    """

    areas: list[Area]
    row_spacing_m: float = 25.0
    tip_spacing_m: float = 3.0
    # Loads placed before the dozer is called. Default is two full rows at the default lattice.
    # Loads between ACCESS passes: grade the ramp, level the floor. Cheap, and it is what decides
    # whether the next truck can get in at all.
    loads_per_dozer_pass: int = 12
    # Loads between FULL passes, which add the crest push and the safety berm on top of an access
    # pass. A berm is by construction a wall, so it is furniture rather than access.
    loads_per_full_pass: int = 60
    # How much a lift raises the working level. A dump is of the order of a metre thick and the dozer
    # spreads it, so a lift is a metre and a half. It is what decides how far each lift is inset from
    # the one below, and therefore the slope of the finished sides.
    lift_thickness_m: float = 1.5
    # The angle those sides stand at. The plan needs it to inset the lifts; the engine imposes it
    # independently through the relaxation, and the two agreeing is the point.
    repose_deg: float = 37.0
    # How far the edge campaign advances its crest per sweep, as a fraction of the load's run-out.
    sweep_advance_frac: float = 0.6
    # Where the upper layer is seeded, as a fraction across the area. The measured pattern seeds near
    # one corner and sweeps outward, so the default is off-centre rather than in the middle.
    seed_frac_x: float = 0.25
    seed_frac_y: float = 0.25

    def area(self, name: str) -> Area:
        for a in self.areas:
            if a.name == name:
                return a
        raise KeyError(f"no area named {name!r}; have {[a.name for a in self.areas]}")

    def area_at(self, x_m: float, y_m: float) -> Area | None:
        for a in self.areas:
            if a.contains(x_m, y_m):
                return a
        return None

    # -- tip generation ---------------------------------------------------------------------

    def paddock_tips(self, area: Area, bench: Bench, *, start_seq: int = 0) -> list[TipPosition]:
        """The base-layer lattice: evenly spaced loads along evenly spaced rows.

        Rows run along +x and are stepped in +y. Alternate rows are walked in the opposite direction,
        which is how a fleet actually works a paddock: the truck that finishes a row is at its far end
        and the next row starts from there. It also matters physically, because consecutive loads come
        from consecutive trucks and therefore from nearby material in the pit, so the serpentine order
        is what puts correlated grades next to each other rather than scattering them.
        """
        rows: list[list[tuple[float, float]]] = []
        # Inset by half a spacing so the lattice sits inside the polygon rather than on its boundary.
        y = area.y0_m + self.row_spacing_m / 2.0
        while y <= area.y1_m:
            xs: list[float] = []
            x = area.x0_m + self.tip_spacing_m / 2.0
            while x <= area.x1_m:
                # THE WHOLE AREA IS FILLED, INCLUDING THE ACCESS CORRIDOR. See `build_ramp`: the ramp
                # is a cut maintained in the fill, not a void reserved in it.
                xs.append(x)
                x += self.tip_spacing_m
            if xs:
                rows.append([(xx, y) for xx in xs])
            y += self.row_spacing_m

        # WORK AWAY FROM THE ACCESS. Rows furthest from the entry point are filled first, so the truck
        # never has to cross material it has already placed. Filling the near rows first walls the
        # machine out of its own dump area, which is what the measured refusals were.
        rows.sort(key=lambda r: -area.distance_from_access(*r[len(r) // 2]))

        tips: list[TipPosition] = []
        seq = start_seq
        for k, row_pts in enumerate(rows):
            # Serpentine: the truck that finishes a row is at its far end and the next row starts
            # from there.
            pts = list(reversed(row_pts)) if k % 2 == 1 else row_pts
            # Heading is along the row, in the direction of travel: the tray discharges behind the
            # truck, so the load lands opposite the way it drove in.
            heading = math.pi if k % 2 == 1 else 0.0
            for xx, yy in pts:
                tips.append(TipPosition(xx, yy, heading, Phase.PADDOCK, area.name, bench.index, seq))
                seq += 1
        return tips

    def edge_tips(
        self,
        area: Area,
        bench: Bench,
        *,
        n_tips: int,
        run_out_m: float,
        start_seq: int = 0,
        lift: int = 0,
    ) -> list[TipPosition]:
        """ONE LIFT of the upper layer: a seed cluster, then radial sweeps outward from it.

        The measured pattern is "radial progression from an initial cluster point" with the material
        added in "sweeping radial movements", and the resulting plot is a set of nested arcs rather
        than rows (Minerals 2021, figure 12). This reproduces that: each sweep is an arc at a fixed
        radius from the seed, clipped to the area, and the radius grows by ``sweep_advance_frac`` of
        the load's run-out per sweep so that successive arcs overlap rather than leaving gaps.

        ``heading_rad`` here is provisional. It is set radially outward from the seed, which is the
        right answer while the face is a growing disc, but the execution step resolves it against the
        live crest normal because that is what the measurement actually specifies.

        ONE CALL IS ONE LIFT, not the whole bench. When the sweeps reach the far corner the area has
        been covered once and the working level has risen by about the thickness of a dump; the next
        lift starts again from the seed. ``lift`` rotates the ring phase so successive lifts do not
        drop every load on the seam left by the one below.
        """
        # SEED OPPOSITE THE ACCESS. The upper layer starts as a cluster and then sweeps outward, so
        # seeding it beside the entry point buries the entry point first and walls the machine out of
        # the area it is meant to be filling. Starting at the far corner makes the crest advance back
        # toward the way out, which is also how a tip head is actually worked.
        corners = [
            (area.x0_m, area.y0_m), (area.x1_m, area.y0_m),
            (area.x0_m, area.y1_m), (area.x1_m, area.y1_m),
        ]
        fx, fy = max(corners, key=lambda p: area.distance_from_access(*p))
        cx0, cy0 = area.centre
        sx = fx + self.seed_frac_x * (cx0 - fx)
        sy = fy + self.seed_frac_y * (cy0 - fy)
        step = max(run_out_m * self.sweep_advance_frac, self.tip_spacing_m)

        tips: list[TipPosition] = []
        seq = start_seq
        # The seed cluster: the first few loads land together to raise the initial crest. Without it
        # there is no face for the first sweep to dump over.
        n_seed = max(3, n_tips // 20)
        for k in range(n_seed):
            if len(tips) >= n_tips:
                break
            a = 2.0 * math.pi * k / max(n_seed, 1)
            r = step * 0.25
            x, y = sx + r * math.cos(a), sy + r * math.sin(a)
            if not area.contains(x, y):
                x, y = sx, sy
            tips.append(TipPosition(x, y, a, Phase.EDGE, area.name, bench.index, seq))
            seq += 1

        ring = 1
        # The area's far corner bounds how far the sweeps can usefully go.
        max_r = math.hypot(max(sx - area.x0_m, area.x1_m - sx), max(sy - area.y0_m, area.y1_m - sy))
        while len(tips) < n_tips and ring * step <= max_r:
            r = ring * step
            # Arc length between tips is held at the lattice spacing, so outer sweeps carry more loads
            # than inner ones. That is the correct behaviour: a longer crest needs more dumps to
            # advance it by the same amount.
            n_on_ring = max(4, int(2.0 * math.pi * r / self.tip_spacing_m))
            for k in range(n_on_ring):
                if len(tips) >= n_tips:
                    break
                a = 2.0 * math.pi * (k + 0.5 * (lift % 2)) / n_on_ring
                x, y = sx + r * math.cos(a), sy + r * math.sin(a)
                if not area.contains(x, y):
                    continue
                tips.append(TipPosition(x, y, a, Phase.EDGE, area.name, bench.index, seq))
                seq += 1
            ring += 1
        return tips

    def bench_program(
        self,
        area: Area,
        bench: Bench,
        *,
        load_volume_m3: float,
        run_out_m: float,
        paddock_frac: float = 0.35,
    ) -> list[TipPosition]:
        """The full ordered program for one bench: the paddock campaign, then the edge campaign.

        ``paddock_frac`` is how much of the bench's designed volume goes down as base layer before the
        upper layer starts. The source describes the base layer as "a series of paddock dumps" without
        quantifying it, so this is an exposed parameter with a stated default rather than a number
        presented as measured.

        A BENCH IS FILLED IN LIFTS, not in one layer, and that is the whole correction here. A dump is
        of the order of a metre thick and a bench is tens of metres tall, so covering the area once
        gets nowhere near the designed volume. The first version emitted exactly one paddock lattice
        and one set of sweeps and then declared the programme complete: on the reference scenario that
        was 332 tips against a design of 1360, so 228 of 560 offered loads were refused with "this
        area is built out" while the pile stood at 10.8 m of a designed 36. The area is covered
        repeatedly, each pass laid on top of the last, until the designed volume is met.
        """
        total_loads = max(1, round(bench.designed_volume_m3 / load_volume_m3))
        n_paddock_target = round(total_loads * paddock_frac)

        # The base layer, on the FULL footprint. It is the floor everything else is built on.
        paddock: list[TipPosition] = []
        while len(paddock) < n_paddock_target:
            batch = self.paddock_tips(area, bench, start_seq=len(paddock))
            if not batch:
                break
            paddock.extend(batch[: n_paddock_target - len(paddock)])

        # THE LIFTS CLIMB A SHRINKING FOOTPRINT. Each one sits inside the one below by the horizontal
        # run of a face at repose, which is what gives the finished solid its sides and what turns
        # the designed frustum volume into an actual frustum instead of a slab of the same volume.
        run_per_lift = self.lift_thickness_m / math.tan(math.radians(self.repose_deg))
        out: list[TipPosition] = list(paddock)
        lift = 0
        while len(out) < total_loads:
            face = area.inset(lift * run_per_lift)
            if face.width_m < 2.0 * self.tip_spacing_m or face.length_m < 2.0 * self.tip_spacing_m:
                break
            # THE SWEEP CARRIES WHAT ITS OWN FOOTPRINT HOLDS AT ONE LIFT THICKNESS, and no more.
            # Letting the sweep run until the ring lattice was exhausted made every lift as thick as
            # its coverage allowed, which on the full footprint is nearly three metres against an
            # inset sized for one and a half. The first two or three lifts then consumed the whole
            # load budget on the widest part of the solid and the pile never climbed: same volume,
            # same 14.6 m peak, whether the lifts were inset or not.
            n_lift = max(1, round(face.plan_area_m2 * self.lift_thickness_m / load_volume_m3))
            # THE SWEEP SPACING IS THE LIFT'S RUN-OUT, NOT THE BENCH'S. A sweep advances by a
            # fraction of the run-out, and passing the whole bench face here spaced the rings twenty
            # metres apart on a lift a metre and a half thick. Each lift then produced a third of the
            # tips its own footprint holds, the programme ran out at 551 tips against a designed 766,
            # and the shortfall came back as "this area is built out" while nothing had been refused
            # for access at all. The material still cascades down whatever face the TERRAIN presents;
            # this is the lattice, not the physics.
            lift_run_out = self.lift_thickness_m / math.tan(math.radians(self.repose_deg))
            sweep = self.edge_tips(
                face, bench, n_tips=min(total_loads - len(out), n_lift), run_out_m=lift_run_out,
                start_seq=len(out), lift=lift,
            )
            if not sweep:
                break
            out.extend(sweep)
            lift += 1
        return out

    def program(
        self, *, load_volume_m3: float, run_out_m: float, paddock_frac: float = 0.35
    ) -> list[TipPosition]:
        """Every tip position for the whole design, area by area, bench by bench, in build order.

        Benches are completed within an area before the next area starts, matching the practice of
        building one pile per material class at a time.
        """
        out: list[TipPosition] = []
        for a in self.areas:
            for b in sorted(a.benches, key=lambda x: x.index):
                out.extend(
                    self.bench_program(
                        a,
                        b,
                        load_volume_m3=load_volume_m3,
                        run_out_m=run_out_m,
                        paddock_frac=paddock_frac,
                    )
                )
        return out


def _frustum_m3(w: float, l: float, h: float, repose_deg: float) -> float:
    """Volume of a rectangular frustum of height ``h`` on a ``w`` by ``l`` base at repose.

    Prismatoid rule. The top face is inset by ``h / tan(repose)`` on every side and clamps at zero,
    which turns the frustum into a pyramid once the height is enough to close it.
    """
    inset = h / math.tan(math.radians(repose_deg))
    wt = max(w - 2.0 * inset, 0.0)
    lt = max(l - 2.0 * inset, 0.0)
    mid_w = (w + wt) / 2.0
    mid_l = (l + lt) / 2.0
    return (h / 6.0) * (w * l + 4.0 * mid_w * mid_l + wt * lt)


def rectangular_yard(
    *,
    n_areas: int,
    area_width_m: float,
    area_length_m: float,
    bench_height_m: float,
    n_benches: int,
    gap_m: float = 20.0,
    classes: list[str] | None = None,
    repose_deg: float = 37.0,
    ramp_width_m: float = 25.0,
    margin_m: float = 30.0,
) -> DumpPlan:
    """A stockyard of ``n_areas`` rectangular areas side by side, each with a bench schedule.

    A BENCH IS NOT A BOX and its designed volume is not a fudged fraction of one. Its sides stand at
    the angle of repose, so the solid is a rectangular frustum and its volume follows from the
    footprint, the height and the repose angle by the prismatoid rule. That is computed here rather
    than approximated by a constant, because the constant was wrong in the direction that matters:
    a blunt 0.55 asked a 60 m square to hold 51,500 cubic metres of a shape whose geometric capacity
    at repose is 27,100, so the plan kept issuing tips for material the pile could not hold, the
    surplus spread past the area boundary, and the refusal rate stopped meaning anything.

    Where the height is enough to close the frustum to a point the solid is a pyramid, and the
    formula degrades to that on its own.

    The default geometry is close to the published example: 150 m by 57 m areas with an 8.7 m bench
    approximate the wet-season stockpiles in CCG 2006, and the 150 m by 150 m by 5 m heaped fill of
    Minerals 2021 is the other documented shape.
    """
    labels = classes or [f"A{k + 1}" for k in range(n_areas)]
    if len(labels) < n_areas:
        raise ValueError(f"{n_areas} areas requested but only {len(labels)} class labels given")

    # THE AREAS ARE OFFSET FROM THE PAD ORIGIN. They used to sit flush against it, so a dump on the
    # south or west edge cascaded straight off the grid and the load was refused for having nowhere
    # to land: measured 221 of 766 planned tips on the reference scenario, which is a fifth of the
    # campaign lost to the edge of an array. A dump area has ground around it in every direction,
    # because that is where the run-out goes and where the haul road runs.
    areas: list[Area] = []
    for k in range(n_areas):
        x0 = margin_m + k * (area_width_m + gap_m)
        a = Area(
            name=labels[k],
            x0_m=x0,
            y0_m=margin_m,
            x1_m=x0 + area_width_m,
            y1_m=margin_m + area_length_m,
            material_class=labels[k],
            ramp_width_m=ramp_width_m,
        )
        per_bench = _frustum_m3(area_width_m, area_length_m, bench_height_m, repose_deg)
        a.benches = [
            Bench(index=b, top_m=(b + 1) * bench_height_m, designed_volume_m3=per_bench)
            for b in range(n_benches)
        ]
        areas.append(a)
    return DumpPlan(areas=areas, repose_deg=repose_deg)
