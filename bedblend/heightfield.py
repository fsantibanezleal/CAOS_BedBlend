"""Method 1, the mass-conserving relaxation solver with an imposed angle of repose.

WHAT THIS IS. A height field ``h[i, j]`` receives material at a point and relaxes until no local
slope exceeds a critical value. The toppling rule is the one Bak, Tang and Wiesenfeld introduced for
the sandpile automaton (Phys. Rev. Lett. 59(4), 381-384, 1987, doi:10.1103/PhysRevLett.59.381).

WHAT THIS IS NOT, said plainly because the distinction is easy to blur. BTW is a model of avalanche
size statistics under self-organized criticality, in which the critical slope is a free parameter of
the automaton and the interesting result is a power law. None of that is claimed here. Here the
critical slope is IMPOSED as the material's angle of repose, taken from published handbook ranges
(about 34 to 60 degrees for ores), and the toppling rule is used only as a mass-conserving relaxation
solver. Avalanche statistics are out of scope.

WHY IT MATTERS FOR THE PRODUCT. The relaxation is not decoration around the interesting part; it IS
the mechanism that carries material away from the dump point and down the flank, and the ordered
chain of transfers it produces is the avalanche path along which size segregation acts. Methods 1, 4
and 8 are coupled through this function's return value.

TWO INVARIANTS, both enforced by tests rather than asserted in prose:
  * mass is conserved to machine precision, because every transfer subtracts and adds the same float;
  * after convergence, no local slope exceeds the imposed repose angle beyond the tolerance.
"""
from __future__ import annotations

import heapq
import math

# 8-neighbourhood offsets: the four orthogonal directions then the four diagonals. A 4-neighbourhood
# builds visibly square cones, which is a solver artefact a reader would rightly read as a bug.
_OFFSETS: tuple[tuple[int, int], ...] = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)

MAX_MOVES = 200_000   # a hard backstop; a converged cascade uses a tiny fraction of this
CONVERGE_TOL_M = 1e-9


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


def neighbour_table(nx: int, ny: int, cell_m: float, repose_deg: float) -> list[list[tuple[int, float]]]:
    """Precomputed ``(neighbour_index, admissible_drop)`` per cell, cached per pad geometry.

    Building this list inside the relaxation loop was the single largest cost in the whole engine:
    a cascade sweeps thousands of cells, and allocating a fresh eight-element list of tuples for each
    of them, on every sweep, on every one of several hundred dumps, dominated everything the science
    was doing. The table depends only on the pad and the repose angle, so it is built once and shared.

    The pad edge is a wall. Material reaching the boundary stays on the pad rather than falling off
    it, which keeps mass conservation exact; a pile that touches the boundary is flagged by the caller
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
    if len(_NBR_CACHE) > 8:
        _NBR_CACHE.clear()  # a session sweeps few pad geometries; do not grow without bound
    _NBR_CACHE[key] = table
    return table


def cascade(
    h: list[float],
    nx: int,
    ny: int,
    cell_m: float,
    repose_deg: float,
    *,
    active: set[int] | None = None,
    max_moves: int = MAX_MOVES,
) -> list[tuple[int, int, float]]:
    """Relax ``h`` in place and return the transfers IN DOWNSLOPE ORDER.

    THE ORDER IS THE POINT. The returned sequence is the avalanche path: the highest unstable cell
    topples first, then whatever it destabilised, and so on down the flank. That ordering is the
    downslope coordinate the segregation solver marches along, so this function's return value is what
    couples methods 1, 4 and 8 together.

    HOW A CELL TOPPLES. Exactly to its repose surface, in one step. Let the cell give away a total
    ``T`` split as ``t_k = max(0, d_k - T)`` over its over-steep neighbours. Every constraint is then
    satisfied simultaneously and none is overshot, and ``T`` solves the water-filling equation
    ``T = sum_k max(0, d_k - T)``, which for the ``k`` largest excesses is ``T = (sum of those k) /
    (k + 1)``.

    WHY A PRIORITY CASCADE RATHER THAN SWEEPS. Two earlier versions of this function were too slow to
    ship, and both for the same reason. Simultaneous (Jacobi) sweeps let a cell receive from several
    neighbours at once and overshoot above the neighbour it had just fed, so the pair traded material
    back and forth: a cone that should relax in about eight steps took over a hundred sweeps and tens
    of thousands of transfers. Processing the HIGHEST unstable cell first, and applying its transfer
    immediately, makes the relaxation march monotonically downhill and removes the ping-pong entirely.
    The heap holds ``(-height, cell)`` with lazy invalidation: a stale entry is recognised because the
    cell is no longer unstable, and is dropped.

    ``active`` seeds the cascade with the cells a deposit actually touched; a cell that was stable and
    was not touched cannot have become unstable, so nothing is missed by not scanning the pad.
    """
    table = neighbour_table(nx, ny, cell_m, repose_deg)
    seeds = active if active is not None else range(nx * ny)
    heap: list[tuple[float, int]] = [(-h[c], c) for c in seeds]
    heapq.heapify(heap)
    queued: set[int] = set(seeds)
    moves: list[tuple[int, int, float]] = []

    while heap and len(moves) < max_moves:
        _, c = heapq.heappop(heap)
        queued.discard(c)
        hc = h[c]
        over: list[tuple[int, float]] = []
        for n, drop in table[c]:
            d = hc - h[n] - drop
            if d > CONVERGE_TOL_M:
                over.append((n, d))
        if not over:
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
        for n, d in over[:k_active]:
            t = d - level
            if t <= CONVERGE_TOL_M:
                continue
            h[c] -= t
            h[n] += t
            moves.append((c, n, t))
            if n not in queued:
                queued.add(n)
                heapq.heappush(heap, (-h[n], n))
        if c not in queued:
            queued.add(c)
            heapq.heappush(heap, (-h[c], c))

    return moves


def max_slope_excess(h: list[float], nx: int, ny: int, cell_m: float, repose_deg: float) -> float:
    """Largest amount, in metres, by which any local drop exceeds the admissible one.

    The convergence test. A relaxed field returns a value at or below ``CONVERGE_TOL_M``; anything
    larger means the cascade was cut short and the pile is standing steeper than the material can.
    """
    table = neighbour_table(nx, ny, cell_m, repose_deg)
    worst = 0.0
    for c in range(nx * ny):
        hc = h[c]
        for n, drop in table[c]:
            d = hc - h[n] - drop
            worst = max(worst, d)
    return worst
