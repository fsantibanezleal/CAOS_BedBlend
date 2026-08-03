"""Haul trucks as entities: a route over ground they can actually drive, a spot, and a departure.

THE TRUCK IS THE SYSTEM, NOT AN EVENT. The previous engine had a ``TruckDump`` record with a cycling
identifier that meant nothing: material appeared at a coordinate with no machine, no approach and no
exit. A load does not appear from nothing. It arrives on a vehicle that had to reach the tip, position
itself, discharge, and leave, and every one of those steps is constrained by the pile it is building.

THE CYCLE, which is the standard one in dispatch and haulage simulation:

    load at shovel -> haul loaded -> queue at the dump -> SPOT -> discharge
                   -> haul empty -> queue at the shovel -> spot -> load

SPOTTING IS WHERE THE PHYSICS ENTERS. Spotting is the reversing manoeuvre that fixes the truck's
position and heading relative to the crest, and those two quantities are exactly what decide the shape
of the resulting deposit: distance to the crest selects the dump profile, and the crest normal
orients it. So the angle of attack is not decoration on top of the model, it is an input to it.

ACCESS IS A CONSTRAINT, NOT A GIVEN. Routes are solved over the trafficable surface, which is derived
from the pile's own elevation. A tip position on top of a fresh heap has no route to it and is refused
rather than silently served. This is the loop that makes a stockpile impossible to feed repeatedly at
one point: placing a load raises the ground, and raised ground stops being drivable.

WHY THE WHOLE PATH IS RETAINED. The approach and the departure are kept as polylines, not just the
dump coordinate, because the record a real operation holds is a GPS track and because the product has
to be able to draw the truck coming in and going away. A model that stores only the discharge point
cannot show either, and cannot be checked against a fleet-management export.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from enum import Enum

from .design import TipPosition
from .terrain import Terrain, TruckSpec


class CycleState(str, Enum):
    """Where a truck is in its haul cycle."""

    LOADING = "loading"
    HAUL_LOADED = "haul_loaded"
    QUEUED_AT_DUMP = "queued_at_dump"
    SPOTTING = "spotting"
    DUMPING = "dumping"
    HAUL_EMPTY = "haul_empty"
    QUEUED_AT_SHOVEL = "queued_at_shovel"


@dataclass
class Payload:
    """What the truck is carrying, and where it came from.

    ``source_block`` is the ore-control pattern the material was dug from. It is the reason
    consecutive loads are correlated: they come from the same dig block, so the autocorrelation of the
    stream arriving at the pile is a consequence of the shovel's dwell, not a parameter someone typed.

    ``grade_uncertainty`` carries the ore-control classification error forward. Misclassification of
    ore to waste or waste to ore from sampling error alone runs 5 to 20 percent for base and precious
    metal mines (Minerals 2021, section 1.6), so a model that presents a crisp grade per load is
    hiding a known error rather than reporting one.
    """

    tonnes: float
    grade: float
    source_block: int
    grade_uncertainty: float = 0.0


@dataclass
class Route:
    """A drivable polyline in pad metres, with the arc lengths needed to interpolate along it."""

    points: list[tuple[float, float]] = field(default_factory=list)

    @property
    def length_m(self) -> float:
        return sum(
            math.dist(self.points[k], self.points[k + 1]) for k in range(len(self.points) - 1)
        )

    def position_at(self, frac: float) -> tuple[float, float]:
        """Point a given fraction of the way along the route, for animating an approach."""
        if not self.points:
            return 0.0, 0.0
        if len(self.points) == 1 or frac <= 0.0:
            return self.points[0]
        if frac >= 1.0:
            return self.points[-1]
        want = frac * self.length_m
        run = 0.0
        for k in range(len(self.points) - 1):
            a, b = self.points[k], self.points[k + 1]
            seg = math.dist(a, b)
            if run + seg >= want and seg > 0:
                u = (want - run) / seg
                return a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])
            run += seg
        return self.points[-1]

    def heading_at_end(self) -> float:
        """Direction of travel over the final segment, which is the truck's approach heading."""
        if len(self.points) < 2:
            return 0.0
        a, b = self.points[-2], self.points[-1]
        return math.atan2(b[1] - a[1], b[0] - a[0])


@dataclass
class Truck:
    """One machine, its state, and the paths it has driven.

    ``approach`` and ``departure`` are retained after the dump so the product can draw the truck
    coming in and going away, which is what the record of a real operation looks like.
    """

    truck_id: int
    spec: TruckSpec
    x_m: float = 0.0
    y_m: float = 0.0
    heading_rad: float = 0.0
    state: CycleState = CycleState.QUEUED_AT_SHOVEL
    payload: Payload | None = None
    approach: Route = field(default_factory=Route)
    departure: Route = field(default_factory=Route)
    assigned_tip: TipPosition | None = None

    def discharge_xy(self) -> tuple[float, float]:
        """Where the material actually lands, which is NOT where the truck is standing.

        A rear-dump truck tips behind itself and then drives away forward. Placing the load at the
        truck's own coordinate puts the machine on top of its own load, and the consequence is not
        cosmetic: the next thing the model does is solve a departure route from a cell that the load
        just made undrivable, so the truck strands itself every single cycle.

        The offset is measured from the truck's centre to behind the tail. Two thirds of a body length
        puts the release point just off the back of the machine.
        """
        off = 0.66 * self.spec.body_length_m
        return (
            self.x_m + math.cos(self.heading_rad) * off,
            self.y_m + math.sin(self.heading_rad) * off,
        )


class NoRoute(Exception):
    """Raised when a tip position cannot be reached over drivable ground.

    A named exception because refusing an unreachable tip is a RESULT, not an error to be swallowed.
    It is the model correctly reporting that the pile has grown over its own access, and the caller is
    expected to pick another tip.
    """


def passable_mask(terrain: Terrain, max_grade: float) -> list[bool]:
    """Can a truck STAND here: the local surface gradient, by central differences.

    NOT the steepest drop to any neighbour, and the difference is the whole behaviour of the model.
    `Terrain.gradient` returns the worst drop in the 8-neighbourhood, which is the right measure for
    an angle-of-repose check and the wrong one for trafficability: it makes every cell at the top of
    a face and every cell at its foot impassable, because each has one steep neighbour. A pile at
    repose therefore had its entire perimeter, its whole crest and the toe of every face marked as
    ground no truck could occupy, so the working level was unreachable BY CONSTRUCTION. Measured: a
    clean 8 m platform with a correctly graded 0.5 ramp cut into it came out with 30 of 1296 cells
    reachable, and the ramp cells themselves read as impassable while their along-ramp gradient was
    exactly at the limit, because the spoil beside them was not.

    A central difference asks what a truck actually cares about: how the ground tilts underneath it.
    Whether the NEXT cell can be driven to is a separate question, and it is asked separately, per
    step, by the flood fill and the router.

    Computing it once per pad rather than per A* edge visit is what keeps a build at tens of seconds
    instead of hundreds.
    """
    out = [True] * terrain.n_cells
    nx, ny, cm = terrain.nx, terrain.ny, terrain.cell_m
    z = terrain.z
    for j in range(ny):
        for i in range(nx):
            c = j * nx + i
            xa = z[j * nx + max(i - 1, 0)]
            xb = z[j * nx + min(i + 1, nx - 1)]
            ya = z[max(j - 1, 0) * nx + i]
            yb = z[min(j + 1, ny - 1) * nx + i]
            dx = (xb - xa) / (cm * (2.0 if 0 < i < nx - 1 else 1.0))
            dy = (yb - ya) / (cm * (2.0 if 0 < j < ny - 1 else 1.0))
            out[c] = math.hypot(dx, dy) <= max_grade
    return out


def step_ok(terrain: Terrain, a: int, b: int, max_grade: float) -> bool:
    """Can a truck drive from cell ``a`` to adjacent cell ``b``.

    The gradient of the STEP, which is what a machine climbs. A cell being at the lip of a face says
    nothing about whether the move along the lip is drivable.
    """
    ai, aj = terrain.ij(a)
    bi, bj = terrain.ij(b)
    run = terrain.cell_m * (math.sqrt(2.0) if ai != bi and aj != bj else 1.0)
    return abs(terrain.z[b] - terrain.z[a]) / run <= max_grade


def reachable_mask(
    terrain: Terrain,
    start: tuple[float, float],
    max_grade: float,
    *,
    passable: list[bool] | None = None,
) -> list[bool]:
    """Every cell a truck can get to from ``start``, by flood fill over drivable ground.

    WHY A FLOOD FILL RATHER THAN REPEATED ROUTING. Choosing where a truck can actually spot means
    asking "is this reachable" for many candidate positions. Answering that with one A* solve per
    candidate is quadratic and was measured taking a build from 40 seconds to over 500. One flood fill
    answers it for every cell on the pad at once, after which a single A* solve produces the path.

    Cells adjacent to the reachable set are included even when they are themselves too steep to stand
    on, because a truck spots AT the edge of a face: the crest cell it tips over is by definition
    steep on one side, and excluding it would make edge dumping impossible.
    """
    ok = passable if passable is not None else passable_mask(terrain, max_grade)
    s = terrain.cell_at(*start)
    out = [False] * terrain.n_cells
    if s is None or not ok[s]:
        return out

    out[s] = True
    stack = [s]
    while stack:
        c = stack.pop()
        for n in terrain.neighbours(c):
            if out[n] or not ok[n]:
                continue
            # BOTH TESTS, and they are different questions: can the truck stand there, and can it
            # get there from here. A gentle shelf on the far side of a 6 m step is standable and
            # unreachable, and only the per-step test says so.
            if step_ok(terrain, c, n, max_grade):
                out[n] = True
                stack.append(n)
    # One ring of edge cells: standing at the lip of a face is exactly what an edge dump requires.
    fringe = [
        n for c in range(terrain.n_cells) if out[c]
        for n in terrain.neighbours(c) if not out[n]
    ]
    for n in fringe:
        out[n] = True
    return out


def solve_route(
    terrain: Terrain,
    start: tuple[float, float],
    goal: tuple[float, float],
    *,
    max_grade: float,
    simplify: bool = True,
    passable: list[bool] | None = None,
) -> Route:
    """A shortest drivable path from ``start`` to ``goal``, as A* over the trafficable cells.

    Cost is true travel distance, so diagonal steps cost sqrt(2) cells rather than one; using a step
    count instead produces the staircase paths that make a route drawing look like a bug. The
    heuristic is straight-line distance, which is admissible on this cost, so the path is optimal.

    THE GOAL CELL ITSELF IS EXEMPT from the gradient test. A truck spots at the crest, and the crest is
    by definition steep on one side; requiring the discharge cell to be flat would make it impossible
    to ever tip over an edge, which is the whole of the edge-dumping campaign.
    """
    s = terrain.cell_at(*start)
    g = terrain.cell_at(*goal)
    if s is None or g is None:
        raise NoRoute(f"start {start} or goal {goal} is off the pad")
    ok = passable if passable is not None else passable_mask(terrain, max_grade)
    if not ok[s]:
        raise NoRoute(f"the truck cannot stand at its start {start}")

    def h(c: int) -> float:
        ax, ay = terrain.xy(c)
        bx, by = terrain.xy(g)
        return math.hypot(bx - ax, by - ay)

    open_heap: list[tuple[float, int]] = [(h(s), s)]
    came: dict[int, int] = {}
    best: dict[int, float] = {s: 0.0}
    seen: set[int] = set()

    while open_heap:
        _, c = heapq.heappop(open_heap)
        if c == g:
            break
        if c in seen:
            continue
        seen.add(c)
        cx, cy = terrain.xy(c)
        for n in terrain.neighbours(c):
            if n != g and not ok[n]:
                continue
            # The step has to be climbable, not just the ground standable. Same rule as the flood
            # fill, so "reachable" and "routable" cannot disagree and strand a load the mask
            # promised was servable.
            if n != g and not step_ok(terrain, c, n, max_grade):
                continue
            nx_, ny_ = terrain.xy(n)
            step = math.hypot(nx_ - cx, ny_ - cy)
            cand = best[c] + step
            if cand < best.get(n, float("inf")):
                best[n] = cand
                came[n] = c
                heapq.heappush(open_heap, (cand + h(n), n))

    if g not in came and g != s:
        raise NoRoute(
            f"no drivable route to {goal}: the pile has grown over its own access, "
            f"or the tip sits on ground steeper than the equipment limit"
        )

    chain = [g]
    while chain[-1] != s:
        chain.append(came[chain[-1]])
    chain.reverse()
    pts = [terrain.xy(c) for c in chain]
    return Route(_simplify(pts) if simplify else pts)


def _simplify(points: list[tuple[float, float]], tol: float = 1e-6) -> list[tuple[float, float]]:
    """Drop interior points that lie on a straight run, so a route is a polyline and not a cell dump.

    A grid path has one point per cell, which is both heavy to store and misleading to draw: it
    suggests the truck is making decisions it is not. Collinear runs collapse to their endpoints.
    """
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    for k in range(1, len(points) - 1):
        ax, ay = out[-1]
        bx, by = points[k]
        cx, cy = points[k + 1]
        # Cross product of the two segments; zero means the three are collinear.
        if abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) > tol:
            out.append(points[k])
    out.append(points[-1])
    return out


def spot(
    terrain: Terrain,
    approach: Route,
    tip: TipPosition,
    *,
    crest: list[int] | None = None,
) -> tuple[float, float]:
    """Resolve the truck's discharge heading, and return ``(heading, distance to crest)``.

    A haul truck rear-dumps, so it reverses into position and the material leaves BEHIND it. The
    discharge direction is therefore opposite the direction the truck drove in, which is why spotting
    is a distinct step and not just an arrival.

    When a crest is in range the heading is taken from the face instead, because the measured rule is
    that the deposit "runs perpendicular to the tangent of the dump location". The terrain wins over
    the plan here: the plan was written before the face moved, and the face is where the material
    actually goes.
    """
    drive_in = approach.heading_at_end()
    discharge = drive_in + math.pi

    if not crest:
        return discharge, float("inf")

    best_d = float("inf")
    best_c = None
    for c in crest:
        cx, cy = terrain.xy(c)
        d = math.hypot(cx - tip.x_m, cy - tip.y_m)
        if d < best_d:
            best_d, best_c = d, c

    if best_c is not None and best_d <= 3.0 * tip_reach(terrain):
        nx_, ny_ = terrain.outward_normal(best_c)
        if abs(nx_) > 1e-12 or abs(ny_) > 1e-12:
            discharge = math.atan2(ny_, nx_)
    return discharge, best_d


def tip_reach(terrain: Terrain) -> float:
    """How far from a crest cell a tip still counts as being at the face, in metres.

    Expressed in cells so it scales with the pad's own resolution rather than being a hidden constant
    that only makes sense at one cell size.
    """
    return 4.0 * terrain.cell_m


@dataclass
class Fleet:
    """A set of trucks working a plan, with the shovel they load at.

    Deliberately NOT a discrete-event simulator. Queue times, bunching and dispatch optimisation are a
    different product; what is needed here is that every load has a machine, a route and a spot, so
    that the geometry it produces is the geometry a real cycle would produce.
    """

    trucks: list[Truck]
    shovel_xy: tuple[float, float]
    max_grade: float

    @classmethod
    def of(
        cls,
        n: int,
        spec: TruckSpec,
        shovel_xy: tuple[float, float],
        *,
        repose_deg: float = 37.0,
        grade_limit_divisor: float = 1.5,
    ) -> Fleet:
        """Build a fleet whose gradient limit is derived, with its provenance stated.

        The divisor is the commonly repeated operational rule of thumb that trucks should not work
        slopes approaching the angle of repose. It is NOT a measured constant, it is exposed here so a
        reader can see and change it, and the product must describe it as a rule of thumb.
        """
        max_grade = math.tan(math.radians(repose_deg)) / grade_limit_divisor
        return cls(
            trucks=[
                Truck(truck_id=k, spec=spec, x_m=shovel_xy[0], y_m=shovel_xy[1]) for k in range(n)
            ],
            shovel_xy=shovel_xy,
            max_grade=max_grade,
        )

    def dispatch(
        self,
        terrain: Terrain,
        truck: Truck,
        tip: TipPosition,
        payload: Payload,
        *,
        crest: list[int] | None = None,
    ) -> tuple[float, float]:
        """Run one truck from the shovel to a tip and out again.

        Returns ``(discharge heading, distance to crest)``, the two quantities the dump operator needs.
        Raises ``NoRoute`` if the tip cannot be reached, which the caller should treat as the plan
        being infeasible at this point in the build rather than as a failure.

        The departure is solved to a DIFFERENT point from the approach where one is given, because a
        truck leaves the tip head by another way rather than reversing back down its own path.
        """
        truck.payload = payload
        truck.state = CycleState.HAUL_LOADED
        truck.approach = solve_route(
            terrain, self.shovel_xy, (tip.x_m, tip.y_m), max_grade=self.max_grade,
            passable=passable_mask(terrain, self.max_grade),
        )

        truck.state = CycleState.SPOTTING
        heading, d_crest = spot(terrain, truck.approach, tip, crest=crest)
        truck.x_m, truck.y_m = tip.x_m, tip.y_m
        truck.heading_rad = heading
        truck.assigned_tip = tip

        truck.state = CycleState.DUMPING
        return heading, d_crest

    def depart(
        self,
        terrain: Terrain,
        truck: Truck,
        *,
        exit_xy: tuple[float, float] | None = None,
    ) -> Route:
        """Send the truck away from the tip, and record the path it took.

        Called after the material has been placed, because the surface the truck leaves over is the
        one its own load just changed. Solving the departure before the dump would let a truck drive
        out across ground that no longer exists.
        """
        target = exit_xy or self.shovel_xy
        truck.payload = None
        truck.state = CycleState.HAUL_EMPTY
        try:
            truck.departure = solve_route(
                terrain, (truck.x_m, truck.y_m), target, max_grade=self.max_grade,
                passable=passable_mask(terrain, self.max_grade),
            )
        except NoRoute:
            # The load just placed can cut off the way out. That is a real and reportable situation:
            # it is how a badly sequenced plan strands equipment. Record an empty departure rather
            # than pretending the truck teleported home.
            truck.departure = Route([(truck.x_m, truck.y_m)])
        truck.x_m, truck.y_m = target
        truck.state = CycleState.QUEUED_AT_SHOVEL
        return truck.departure
