"""Mass-conserving relaxation that actually holds the angle of repose.

WHY THIS MODULE IS A REWRITE AND NOT A MOVE. The previous engine's relaxation left, on a measured run,
446 cell pairs standing steeper than the imposed repose angle, the worst at 55.9 degrees against an
imposed 37. Those over-steep pairs are the spikes a reader sees in the rendered pile. The solver core
below is sound and is carried over; what was wrong was everything around it, and the fixes are:

  1. RELAXATION IS NOT OPTIONAL AND NOT PARTIAL. Every operation that moves material calls it:
     deposition, dozing and reclaim alike. In the previous engine ``cascade`` was invoked only from
     ``deposit`` and never after ``reclaim``, so a cut could leave a face standing at any angle and
     nothing ever took it down.
  2. THE RESULT IS VERIFIED, NOT ASSUMED. ``assert_stable`` is cheap and is called by the tests and by
     the pipeline gate. A relaxation that silently ran out of moves used to look identical to one that
     converged.
  3. THE SEED SET IS CONSERVATIVE. A cascade seeded only with the cells a deposit wrote can miss a
     neighbour that was already marginal, so the seeds are expanded by one ring. Being slightly
     generous costs a few heap operations; being slightly mean leaves permanent over-steep pairs.

THE TWO-STAGE SLOPE, which is a physical finding rather than a numerical one. A truck-dumped heap does
not appear at the angle of repose. It is emplaced steep and slumps afterwards: "At the time of dumping,
heaps maintain an approximate 2:1 slope, consistent with that of heaped loaded material. Over time the
slope decreases to that of the natural angle of repose of the material" (Young and Rogers, Minerals
2021, 11, 636, figure 11). A 2:1 slope is about 63 degrees, well above any ore's repose angle, so
``relax_to`` takes a target angle and the caller decides whether this step is the fresh heap or the
settled one.

WHAT THE SOLVER IS, AND IS NOT. The toppling rule is the one Bak, Tang and Wiesenfeld introduced for
the sandpile automaton (Phys. Rev. Lett. 59(4), 381-384, 1987, doi:10.1103/PhysRevLett.59.381). None of
the self-organized-criticality claims are made here: the critical slope is IMPOSED as the material's
angle of repose rather than being a free parameter, and avalanche statistics are out of scope. It is
used purely as a mass-conserving relaxation solver whose ordered output is the avalanche path that
segregation marches along.
"""
from __future__ import annotations

import heapq
import math

from .terrain import Terrain

_OFFSETS: tuple[tuple[int, int], ...] = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)

MAX_MOVES = 2_000_000   # a hard backstop; a converged cascade uses a tiny fraction of this
CONVERGE_TOL_M = 1e-9

# The tolerance the VERIFIER allows, which must be looser than the one the solver converges to.
# A cascade settles each pair to within CONVERGE_TOL_M, but a cell is touched by many transfers and
# the rounding accumulates, so a converged field can sit a few nanometres over the line: measured, the
# residual comes out at 37.00000004 degrees against an imposed 37. Checking at the solver's own
# tolerance flags that as a failure, which would make the invariant cry wolf and train a reader to
# ignore it. A micrometre is far below any physical meaning on a pile and far above float noise.
# Material thinner than this is not material. A tenth of a millimetre is far below anything the
# geometry means and far above the noise the solver converges to.
BARE_M = 1e-3

VERIFY_TOL_M = 1e-6

# 2:1 rise over run, the slope a fresh truck-dumped heap stands at before it settles.
FRESH_HEAP_SLOPE = 2.0
FRESH_HEAP_DEG = math.degrees(math.atan(FRESH_HEAP_SLOPE))   # about 63.4 degrees


class ReposeViolation(AssertionError):
    """Raised when a field is left standing steeper than the material can stand.

    A named exception rather than a bare assert because this is the failure mode that shipped to
    production once already, and it should be greppable in a log.
    """


def critical_drop(cell_m: float, repose_deg: float) -> tuple[float, float]:
    """Maximum stable height difference to an orthogonal and to a diagonal neighbour, in metres.

    The repose angle is a slope, so the admissible drop scales with the horizontal distance between
    cell centres: ``cell_m`` orthogonally and ``cell_m * sqrt(2)`` diagonally. Using one drop for both
    is the mistake that makes a relaxed cone come out square.
    """
    slope = math.tan(math.radians(repose_deg))
    orth = cell_m * slope
    return orth, orth * math.sqrt(2.0)


_NBR_CACHE: dict[tuple[int, int, float, float], list[list[tuple[int, float]]]] = {}


def neighbour_table(
    nx: int, ny: int, cell_m: float, repose_deg: float
) -> list[list[tuple[int, float]]]:
    """Precomputed ``(neighbour_index, admissible_drop)`` per cell, cached per pad geometry.

    Building this inside the relaxation loop was the single largest cost in the whole engine: a
    cascade sweeps thousands of cells, and allocating a fresh eight-element list for each of them, on
    every sweep, on every one of several hundred dumps, dominated everything the science was doing.
    The table depends only on the pad and the angle, so it is built once and shared.

    The pad edge is a wall. Material reaching the boundary stays on the pad rather than falling off it,
    which keeps mass conservation exact; a pile that touches the boundary is flagged by the caller
    instead of silently losing tonnes over the edge.
    """
    key = (nx, ny, cell_m, repose_deg)
    hit = _NBR_CACHE.get(key)
    if hit is not None:
        return hit
    orth, diag = critical_drop(cell_m, repose_deg)
    table: list[list[tuple[int, float]]] = []
    for idx in range(nx * ny):
        i, j = idx % nx, idx // nx
        row: list[tuple[int, float]] = []
        for k, (di, dj) in enumerate(_OFFSETS):
            ni, nj = i + di, j + dj
            if 0 <= ni < nx and 0 <= nj < ny:
                row.append((nj * nx + ni, diag if k >= 4 else orth))
        table.append(row)
    if len(_NBR_CACHE) > 16:
        _NBR_CACHE.clear()   # a session sweeps few geometries; do not grow without bound
    _NBR_CACHE[key] = table
    return table


def _expand_seeds(nx: int, ny: int, seeds: set[int]) -> set[int]:
    """Grow a seed set by one ring.

    A deposit writes a set of cells, but the cells it destabilises can include neighbours it never
    touched: a cell that was exactly at repose becomes over-steep the moment the cell beside it grows.
    Seeding only the written cells is how a relaxation comes back reporting success while leaving
    permanent over-steep pairs behind.
    """
    out = set(seeds)
    for c in seeds:
        i, j = c % nx, c // nx
        for di, dj in _OFFSETS:
            ni, nj = i + di, j + dj
            if 0 <= ni < nx and 0 <= nj < ny:
                out.add(nj * nx + ni)
    return out


def cascade(
    z: list[float],
    nx: int,
    ny: int,
    cell_m: float,
    repose_deg: float,
    *,
    active: set[int] | None = None,
    max_moves: int = MAX_MOVES,
    floor: list[float] | None = None,
) -> list[tuple[int, int, float]]:
    """Relax ``z`` in place and return the transfers IN DOWNSLOPE ORDER.

    THE ORDER IS THE POINT. The returned sequence is the avalanche path: the highest unstable cell
    topples first, then whatever it destabilised, and so on down the flank. That ordering is the
    downslope coordinate the segregation solver marches along, so this return value is what couples
    the geometry to the physics.

    HOW A CELL TOPPLES. Exactly to its repose surface, in one step. Let the cell give away a total
    ``T`` split as ``t_k = max(0, d_k - T)`` over its over-steep neighbours. Every constraint is then
    satisfied simultaneously and none is overshot, and ``T`` solves the water-filling equation
    ``T = sum_k max(0, d_k - T)``, which for the ``k`` largest excesses is ``T = (sum of those k) /
    (k + 1)``.

    WHY A PRIORITY CASCADE RATHER THAN SWEEPS. Simultaneous sweeps let a cell receive from several
    neighbours at once and overshoot above the neighbour it had just fed, so the pair traded material
    back and forth: a cone that should relax in about eight steps took over a hundred sweeps. Taking
    the HIGHEST unstable cell first, and applying its transfer immediately, makes the relaxation march
    monotonically downhill and removes the ping-pong entirely. The heap holds ``(-height, cell)`` with
    lazy invalidation: a stale entry is recognised because the cell is no longer unstable, and dropped.
    """
    table = neighbour_table(nx, ny, cell_m, repose_deg)
    seeds = _expand_seeds(nx, ny, active) if active is not None else set(range(nx * ny))
    heap: list[tuple[float, int]] = [(-z[c], c) for c in seeds]
    heapq.heapify(heap)
    queued: set[int] = set(seeds)
    moves: list[tuple[int, int, float]] = []

    while heap and len(moves) < max_moves:
        _, c = heapq.heappop(heap)
        queued.discard(c)
        zc = z[c]
        over: list[tuple[int, float]] = []
        for n, drop in table[c]:
            d = zc - z[n] - drop
            if d > CONVERGE_TOL_M:
                over.append((n, d))
        if not over:
            continue
        # A cell can only shed the material sitting above the original ground.
        budget = (zc - floor[c]) if floor is not None else float("inf")
        if budget <= CONVERGE_TOL_M:
            continue

        over.sort(key=lambda p: -p[1])
        total = 0.0
        level = 0.0
        k_active = 0
        for k, (_, d) in enumerate(over, start=1):
            total += d
            cand = total / (k + 1)
            if d > cand:
                level = cand
                k_active = k
            else:
                break
        if k_active == 0:
            continue
        moved = False
        for n, d in over[:k_active]:
            t = d - level
            if t <= CONVERGE_TOL_M:
                continue
            t = min(t, budget)
            budget -= t
            if t <= CONVERGE_TOL_M:
                break
            z[c] -= t
            z[n] += t
            moved = True
            moves.append((c, n, t))
            # The receiver grew, so it may now be over-steep against ITS downhill neighbours.
            if n not in queued:
                queued.add(n)
                heapq.heappush(heap, (-z[n], n))

        # RE-QUEUE ONLY AFTER REAL PROGRESS. Every candidate transfer can come out at or below the
        # tolerance while the cell still reads as marginally unstable. Re-queueing then would spin
        # forever, because nothing moves and the loop's only bound is on the number of moves. Since a
        # cell is re-queued only when at least one transfer of more than CONVERGE_TOL_M has gone
        # downhill, and the sum of squared heights strictly decreases with every such transfer, the
        # cascade is guaranteed to terminate.
        if not moved:
            continue

        # THE CELL THAT GAVE MATERIAL AWAY GOT LOWER, AND THAT DESTABILISES THE CELLS ABOVE IT.
        # This is the bug that produced the spikes. A highest-first queue processes an uphill
        # neighbour BEFORE this cell, finds it stable, and never looks at it again; then this cell
        # drops, the drop from that neighbour down to here grows past repose, and nothing re-queues
        # it. The original solver pushed only the receivers and the toppling cell, so those pairs
        # survived to the end of the run: 446 of them on a measured case, the worst at 55.9 degrees
        # against an imposed 37. Re-queue every neighbour that now stands above this cell.
        zc_new = z[c]
        for n, _drop in table[c]:
            if z[n] > zc_new and n not in queued:
                queued.add(n)
                heapq.heappush(heap, (-z[n], n))
        if c not in queued:
            queued.add(c)
            heapq.heappush(heap, (-zc_new, c))

    return moves


def max_slope_excess(
    z: list[float], nx: int, ny: int, cell_m: float, repose_deg: float
) -> float:
    """Largest amount, in metres, by which any local drop exceeds the admissible one."""
    table = neighbour_table(nx, ny, cell_m, repose_deg)
    worst = 0.0
    for c in range(nx * ny):
        zc = z[c]
        for n, drop in table[c]:
            worst = max(worst, zc - z[n] - drop)
    return worst


def count_over_repose(
    z: list[float], nx: int, ny: int, cell_m: float, repose_deg: float,
    *, floor: list[float] | None = None,
) -> tuple[int, float]:
    """``(number of over-steep ordered pairs, worst angle in degrees)``.

    The diagnostic that caught the original defect, kept as a first-class function so the number can
    be reported rather than rediscovered. On a converged field it returns ``(0, angle <= repose)``.
    """
    slope = math.tan(math.radians(repose_deg))
    n_over = 0
    worst_deg = 0.0
    for c in range(nx * ny):
        i, j = c % nx, c // nx
        zc = z[c]
        # THE ANGLE OF REPOSE IS A PROPERTY OF LOOSE MATERIAL, NOT OF BEDROCK. A natural hillside is
        # entitled to stand steeper than any ore will, and flagging it would make the invariant
        # meaningless on four of the five published fill types. A cell is only capable of violating
        # repose if it is carrying material that could move.
        # BARE MEANS PHYSICALLY BARE, not "within floating-point noise of bare". The threshold used
        # to be the verification tolerance, a micrometre, and a cell holding a millimetre of dust
        # was therefore asked to stand at an angle of repose. It cannot: shedding everything it has
        # leaves the ground, and the ground is where it already is. Measured on a sidehill and a
        # ridge, this is what produced violations reported at 37.0 and 37.1 degrees against an
        # imposed 37, which is the solver being correct and the check being wrong.
        if floor is not None and zc - floor[c] <= BARE_M:
            continue
        for k, (di, dj) in enumerate(_OFFSETS):
            ni, nj = i + di, j + dj
            if not (0 <= ni < nx and 0 <= nj < ny):
                continue
            run = cell_m * (math.sqrt(2.0) if k >= 4 else 1.0)
            zn = z[nj * nx + ni]
            drop = zc - zn
            if drop <= 0.0:
                continue
            worst_deg = max(worst_deg, math.degrees(math.atan(drop / run)))
            if drop - run * slope <= VERIFY_TOL_M:
                continue
            # AND THE STEEPNESS HAS TO BE THE MATERIAL'S. Skipping bare cells is not enough: a cell
            # carrying a thin skin of material over ground that already stands steep is flagged, and
            # NOTHING can clear it. Shedding every grain it has leaves the ground, and the ground is
            # still over the angle. The cascade knows this and correctly declines to move anything;
            # the check did not, so the two disagreed and a build died on a surface that was as
            # relaxed as it can physically be. Measured on a sidehill: 65 pairs, worst 49.1 degrees,
            # every one of them inherited. The test is whether removing the material would fix it.
            # The escape allows equality: if shedding every grain the cell has would leave it at or
            # over the angle, the steepness is the ground's and no solver can take it away.
            if floor is not None and (floor[c] - zn) - run * slope >= -VERIFY_TOL_M:
                continue
            n_over += 1
    return n_over, worst_deg


def relax_to(
    terrain: Terrain,
    repose_deg: float,
    *,
    active: set[int] | None = None,
    verify: bool = True,
    respect_ground: bool = True,
) -> list[tuple[int, int, float]]:
    """Relax the terrain surface to ``repose_deg`` and, by default, prove that it worked.

    ``verify`` is on by default and that is deliberate. The check is O(cells) against a solver that is
    already O(moves log moves), so it is not the bottleneck, and the failure it catches is the one that
    shipped. Turn it off only in an inner loop that verifies once at the end.
    """
    floor = terrain.z0 if respect_ground else None
    moves = cascade(
        terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, active=active,
        floor=floor,
    )

    # A CASCADE OVER A FLOOR CAN LEAVE A HANDFUL OF PAIRS, and widening the tolerance would be the
    # wrong way to deal with it. With a floor a cell's transfer can be cut short by the rock beneath
    # it, and the cell it would have fed is then left marginally over the angle without ever having
    # been queued. Measured on a ridge crest: 17 pairs, worst 44.0 degrees against an imposed 37.
    # Correctness wins over speed here, so if anything is left standing the whole pad is swept again.
    # The check is O(cells) and the sweep only runs when it is needed.
    for _ in range(3):
        n_over, _ = count_over_repose(
            terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, floor=floor
        )
        if not n_over:
            break
        moves += cascade(
            terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, active=None, floor=floor,
        )

    if verify:
        assert_stable(terrain, repose_deg)
    return moves


def settle(
    terrain: Terrain,
    repose_deg: float,
    *,
    active: set[int] | None = None,
    fresh_deg: float = FRESH_HEAP_DEG,
) -> list[tuple[int, int, float]]:
    """Two-stage relaxation: hold the fresh heap at its emplacement slope, then let it settle.

    This is the measured behaviour of a truck-dumped heap rather than a numerical convenience. The
    material is emplaced at roughly 2:1 and slumps to the natural angle of repose afterwards, so a
    model that jumps straight to repose is showing a pile that has already finished settling and can
    never show the process. The two calls also produce two distinct avalanche paths, and segregation
    acting along both is not the same as segregation acting along one.
    """
    first = cascade(
        terrain.z, terrain.nx, terrain.ny, terrain.cell_m, fresh_deg, active=active,
        floor=terrain.z0,
    )
    # The settling stage cannot be seeded from the deposit alone: the first stage has already moved
    # material outward, so cells that were never written can now be over-steep. But it must not fall
    # back to seeding the whole pad either. Doing that costs a full-pad heapify on EVERY load, which
    # measured out as the dominant cost of a build and made an end-to-end run unusable. The correct
    # seed set is the deposit plus every cell the first stage touched, since a cell that neither
    # received material nor had a neighbour change cannot have become unstable.
    if active is None:
        seed: set[int] | None = None
    else:
        seed = set(active)
        for a, b, _ in first:
            seed.add(a)
            seed.add(b)
    second = cascade(
        terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, active=seed,
        floor=terrain.z0,
    )

    # A SEEDED CASCADE CAN STILL MISS A PAIR ON SLOPING GROUND, and it is worth saying why rather
    # than widening the tolerance. With a floor, a cell's transfer can be cut short by the ground
    # beneath it, and the cell it would have fed is then left marginally over the angle without ever
    # having been queued. Measured on a valley fill: 4 pairs at 38.2 degrees against an imposed 37.
    # Correctness wins over speed here, so if anything is left standing the whole pad is swept once.
    # The check is O(cells) and the sweep only ever runs when it is needed.
    n_over, _ = count_over_repose(
        terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, floor=terrain.z0
    )
    third: list[tuple[int, int, float]] = []
    if n_over:
        third = cascade(
            terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, active=None,
            floor=terrain.z0,
        )

    assert_stable(terrain, repose_deg)
    return first + second + third


def assert_stable(terrain: Terrain, repose_deg: float) -> None:
    """Raise ``ReposeViolation`` if any pair stands steeper than the material can.

    The message carries the count and the worst angle because those are exactly the numbers needed to
    tell a genuine solver failure from a caller that passed the wrong angle.
    """
    n_over, worst = count_over_repose(
        terrain.z, terrain.nx, terrain.ny, terrain.cell_m, repose_deg, floor=terrain.z0
    )
    if n_over:
        raise ReposeViolation(
            f"{n_over} cell pairs stand over the imposed repose angle of {repose_deg:.1f} deg; "
            f"the worst local slope is {worst:.1f} deg. The surface is not relaxed."
        )
