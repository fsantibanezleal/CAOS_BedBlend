"""Method 8, the per-cell lot ledger, and the deposition and reclaim mechanics built on it.

THE DATA STRUCTURE. Every pad cell owns an ordered stack of lots, bottom to top. A lot records which
deposition event it came from, how many tonnes it is, its grades, and its coarse fraction. Depositing
pushes onto the stack; the relaxation cascade moves material from the TOP of a source stack to the top
of a destination stack, because that is what a real avalanche does; reclaiming pops according to the
geometry of the reclaim method. A reclaim cut's provenance is then the tonnage-weighted histogram of
the event ids it consumed.

THE PUBLISHED ANALOGUE, cited so the product does not imply it invented this. Zhao, Lu, Koch and
Hurdsman model a stockpile as a grid of voxels each holding a quality composition, and compute the
quality of a bucket-wheel cut in advance from it (Int. J. Miner. Process. 140, 32-42, 2015,
doi:10.1016/j.minpro.2015.04.012; Adv. Eng. Inform. 29(3), 680-695, 2015,
doi:10.1016/j.aei.2015.07.002). The near-real-time version driven by GPS dump and load positions is
Zhao, Lu, Statsenko and Koch, J. Eng. Des. Technol. 20(2), 497-515, 2021,
doi:10.1108/JEDT-12-2020-0541, whose abstract states that tracing ore grade at run-of-mine stockpiles
is hard with current fleet-management systems because the information is not available in real time.
That unsolved practical problem is what this product exists to make visible.

THE INVARIANTS. Provenance fractions of every cut sum to one, and deposited tonnes equal in-pile plus
reclaimed tonnes at every step. Both are tests. A ledger that silently loses or double-counts material
would still produce a plausible picture, which is exactly why the identities are checked numerically.

WHY THE TONNAGE PER COLUMN IS CACHED. Summing a column's lots on demand turns every deposit into a
walk over the whole ledger, and with a few hundred dumps that is the difference between a live
interaction budget and a stalled tab. ``col_t`` is maintained incrementally by every push and pop, and
``check_column_cache`` re-derives it from the lots so a test can prove the cache never drifts.
"""
from __future__ import annotations

import math

from .heightfield import cascade
from .schema import Lot, PadSpec, ReclaimCut, TruckDump
from .segregation import FlowingLayer

MIN_LOT_T = 1e-9
FOOTPRINT_R_M = 4.5  # m, radius over which one truck load lands; a load is not a point source
N_BANDS = 12         # downslope bands the avalanche path is split into for the segregation solve

# A reclaim geometry is two numbers: the fraction of the face WIDTH the machine engages (expressed by
# which cells it touches, see Pile._reclaim_cells) and how far down the column it REACHES in one cut.
# Together they decide how many stacked layers land in the cut, which is the dominant term in the
# variance reduction. Nothing else about the machines matters to the grade of what they take.
RECLAIM_GEOMETRY: dict[str, dict] = {
    # bridge or harrow reclaimer: rakes the whole triangular section, so it crosses every layer
    "fullface":    {"depth": 1.00, "proportional": True,
                    "machine": "bridge or harrow reclaimer, full cross-section"},
    # slewing bucket wheel cutting a bench across a third of the width
    "bucketwheel": {"depth": 0.55, "proportional": False,
                    "machine": "slewing bucket wheel, bench cut"},
    # end reclaim taking the exposed end face, which reaches only the outer shell
    "end":         {"depth": 0.30, "proportional": False,
                    "machine": "end reclaim, exposed end face"},
    # front-end loader biting the accessible face at scattered positions
    "loader":      {"depth": 0.12, "proportional": False,
                    "machine": "front-end loader, scattered bites"},
}


class Pile:
    """The stockpile: a height field, a lot stack per cell, and a cached tonnage per column.

    Deliberately plain lists rather than numpy structured arrays. The same algorithm is mirrored in
    TypeScript for the live browser lane, and a list-of-lists translates one to one, so the two
    implementations can be read side by side when the cross-lane determinism test disagrees.
    """

    __slots__ = (
        "_footprint",
        "_tpm",
        "col_t",
        "deposited_t",
        "h",
        "pad",
        "reclaimed_t",
        "stacks",
        "touched_boundary",
    )

    def __init__(self, pad: PadSpec) -> None:
        self.pad = pad
        n = pad.n_cells
        self.h: list[float] = [0.0] * n
        self.stacks: list[list[Lot]] = [[] for _ in range(n)]
        self.col_t: list[float] = [0.0] * n
        self.deposited_t = 0.0
        self.reclaimed_t = 0.0
        self.touched_boundary = False
        self._tpm = pad.cell_area_m2 * pad.bulk_density_tpm3
        self._footprint = self._build_footprint()

    # ------------------------------------------------------------------ geometry helpers

    def _build_footprint(self) -> list[tuple[int, int, float]]:
        """Offsets and weights of the disc a single truck load lands on.

        A haul truck tips a load that spreads over roughly nine metres, not over one two-metre cell.
        Treating it as a point source puts a thirty-metre spike on one cell, which the relaxation then
        has to demolish over hundreds of sweeps, and which is not what happens on a pad. The weights
        are a cosine bell over the disc, normalised to one.
        """
        r_cells = max(0, int(FOOTPRINT_R_M / self.pad.cell_m))
        out: list[tuple[int, int, float]] = []
        total = 0.0
        for dj in range(-r_cells, r_cells + 1):
            for di in range(-r_cells, r_cells + 1):
                d = math.hypot(di, dj) * self.pad.cell_m
                if d > FOOTPRINT_R_M:
                    continue
                w = 0.5 * (1.0 + math.cos(math.pi * d / FOOTPRINT_R_M))
                out.append((di, dj, w))
                total += w
        return [(di, dj, w / total) for di, dj, w in out] if total > 0 else [(0, 0, 1.0)]

    def cell_of(self, x_m: float, y_m: float) -> int:
        i = min(self.pad.nx - 1, max(0, int(x_m / self.pad.cell_m)))
        j = min(self.pad.ny - 1, max(0, int(y_m / self.pad.cell_m)))
        return j * self.pad.nx + i

    def tonnes_per_metre(self) -> float:
        return self._tpm

    # ------------------------------------------------------------------ read-only views

    @property
    def in_pile_t(self) -> float:
        return sum(self.col_t)

    def column_tonnes(self, c: int) -> float:
        return self.col_t[c]

    def column_grade(self, c: int) -> float:
        t = self.col_t[c]
        if t <= 0.0:
            return 0.0
        return sum(lot.tonnes * lot.grade_cu_pct for lot in self.stacks[c]) / t

    def column_coarse(self, c: int) -> float:
        t = self.col_t[c]
        if t <= 0.0:
            return 0.0
        return sum(lot.tonnes * lot.coarse_frac for lot in self.stacks[c]) / t

    def surface_coarse(self, c: int) -> float:
        """Coarse fraction of the topmost lot, which is what a camera or an operator would see."""
        stack = self.stacks[c]
        return stack[-1].coarse_frac if stack else 0.0

    def check_column_cache(self) -> float:
        """Largest disagreement between the cached column tonnage and the ledger. A test asserts zero."""
        worst = 0.0
        for c, stack in enumerate(self.stacks):
            worst = max(worst, abs(self.col_t[c] - sum(lot.tonnes for lot in stack)))
        return worst

    # ------------------------------------------------------------------ ledger primitives

    def _push(self, c: int, lot: Lot) -> None:
        """Push a lot, coalescing it into the top lot when they came from the same dump.

        Without this the ledger fragments without bound: every avalanche transfer splits the
        straddling lot, so a column accumulates thousands of slivers of the same deposition event and
        the whole simulation goes quadratic. Merging two lots of the SAME event is exactly lossless
        for provenance, and the tonnage-weighted coarse fraction is exactly lossless for species mass,
        so this is a pure performance win with no modelling cost. Lots from DIFFERENT events are never
        merged, because that is precisely the information the product exists to keep.
        """
        stack = self.stacks[c]
        if stack:
            top = stack[-1]
            if top.event_id == lot.event_id:
                t = top.tonnes + lot.tonnes
                stack[-1] = Lot(
                    top.event_id, t, top.grade_cu_pct, top.grade_au_gpt,
                    (top.tonnes * top.coarse_frac + lot.tonnes * lot.coarse_frac) / t,
                    min(top.t_s, lot.t_s),
                )
                self.col_t[c] += lot.tonnes
                self.h[c] = self.col_t[c] / self._tpm
                return
        stack.append(lot)
        self.col_t[c] += lot.tonnes
        self.h[c] = self.col_t[c] / self._tpm

    def _pop_top(self, c: int, tonnes: float) -> list[Lot]:
        """Remove ``tonnes`` from the top of column ``c``, splitting the straddling lot.

        Returns the removed lots in bottom-to-top order, so pushing them onto the destination keeps
        their relative deposition ordering: an avalanche slides a slab, it does not shuffle it.
        """
        want = tonnes
        taken: list[Lot] = []
        stack = self.stacks[c]
        removed = 0.0
        while want > MIN_LOT_T and stack:
            top = stack[-1]
            if top.tonnes <= want + MIN_LOT_T:
                stack.pop()
                taken.append(top)
                want -= top.tonnes
                removed += top.tonnes
            else:
                stack[-1] = Lot(top.event_id, top.tonnes - want, top.grade_cu_pct,
                                top.grade_au_gpt, top.coarse_frac, top.t_s)
                taken.append(Lot(top.event_id, want, top.grade_cu_pct, top.grade_au_gpt,
                                 top.coarse_frac, top.t_s))
                removed += want
                want = 0.0
        self.col_t[c] = max(0.0, self.col_t[c] - removed)
        self.h[c] = self.col_t[c] / self._tpm
        taken.reverse()
        return taken

    def _shift_top(self, c: int, tonnes: float, d_coarse: float) -> None:
        """SHIFT the coarse fraction of the top ``tonnes`` of column ``c`` by ``d_coarse``.

        A shift, not an assignment, and the distinction is the difference between a working model and
        a wrong one. An avalanche does not consist only of the load that triggered it: it also carries
        whatever that load dislodged, which came from earlier dumps with their own size distributions.
        Writing an absolute composition here would stamp the current truck's size split onto older
        material, which destroys exactly the information the ledger exists to keep. It also broke the
        C02 negative control by a quarter of the whole range, which is how it was found.

        What the solver actually produces is a REDISTRIBUTION: the deposited portion is enriched in
        fines by some amount and the travelling portion is depleted by the complementary amount, and
        those two shifts cancel by construction. Applying the shift preserves each lot's own identity
        and is exactly neutral when the solver is switched off.

        Grades are untouched. Grade rides with the material; only the size split is redistributed by
        kinetic sieving.

        The lot the flowing depth ends part-way through is shifted in proportion to the share of it
        that is flowing, rather than being split. That keeps the ledger from fragmenting, at the cost
        of resolving the shift at lot granularity, which is far below the resolution anything in the
        product reads at.
        """
        if abs(d_coarse) < 1e-15:
            return
        want = tonnes
        stack = self.stacks[c]
        k = len(stack) - 1
        while want > MIN_LOT_T and k >= 0:
            lot = stack[k]
            share = 1.0 if lot.tonnes <= want + MIN_LOT_T else want / lot.tonnes
            new_cf = min(1.0, max(0.0, lot.coarse_frac + d_coarse * share))
            stack[k] = Lot(lot.event_id, lot.tonnes, lot.grade_cu_pct, lot.grade_au_gpt,
                           new_cf, lot.t_s)
            want -= lot.tonnes
            k -= 1

    # ------------------------------------------------------------------ deposition

    def deposit(self, dump: TruckDump, *, sr: float, nz: int = 32) -> int:
        """Place one truck load and run its avalanche. Returns the number of downslope bands used.

        The three coupled methods meet here. The load lands over a disc footprint as lots on the pad
        (method 8); the height field relaxes and the ordered cascade of transfers IS the avalanche
        path (method 1); a flowing layer marches one step per generation and decides how the fine and
        coarse species split between the material that stops and the material that keeps going
        (method 4).

        Ordering is deliberate: the relaxation runs FIRST on the height field, and the ledger is then
        made to follow it. Moving lots first and hoping the heights agree is how a ledger drifts out
        of step with the geometry it is supposed to describe.

        The per-generation split fraction is physical rather than tuned. Of the tonnage that ARRIVED
        at this generation, the part that does not leave again has stopped here, and that ratio is
        exactly the fraction of the flowing layer handed to the static bed. The layer's base is
        fine-rich, so what stops is fine-rich and what travels on is coarse-rich. Coarse at the toe is
        therefore an output of the solver, not a rule written into it.
        """
        pad = self.pad
        ci = min(pad.nx - 1, max(0, int(dump.x_m / pad.cell_m)))
        cj = min(pad.ny - 1, max(0, int(dump.y_m / pad.cell_m)))

        active: set[int] = set()
        placed = 0.0
        for di, dj, w in self._footprint:
            i, j = ci + di, cj + dj
            if not (0 <= i < pad.nx and 0 <= j < pad.ny):
                continue
            c = j * pad.nx + i
            t = dump.tonnes * w
            if t <= MIN_LOT_T:
                continue
            self._push(c, Lot(dump.event_id, t, dump.grade_cu_pct, dump.grade_au_gpt,
                              dump.coarse_frac, dump.t_s))
            placed += t
            active.add(c)
        if placed < dump.tonnes - MIN_LOT_T and active:
            # the footprint was clipped by the pad edge; the remainder lands on the centre cell so
            # the mass balance stays exact rather than quietly losing the overhang
            c = cj * pad.nx + ci
            self._push(c, Lot(dump.event_id, dump.tonnes - placed, dump.grade_cu_pct,
                              dump.grade_au_gpt, dump.coarse_frac, dump.t_s))
        self.deposited_t += dump.tonnes

        moves = cascade(self.h, pad.nx, pad.ny, pad.cell_m, pad.repose_deg, active=active)
        if not moves:
            return 0

        # The cascade is already in downslope order, so it is banded into a fixed number of steps
        # along the path. A fixed count keeps the segregation solve cheap and, more importantly, keeps
        # the non-dimensional path length equal to one whatever the avalanche's size, which is what
        # makes the segregation number Sr comparable between a small dump and a large one.
        n_bands = min(N_BANDS, len(moves))
        band = len(moves) / n_bands
        layer = FlowingLayer(phi0=1.0 - dump.coarse_frac, sr=sr, nz=nz)
        dx_nd = 1.0 / n_bands
        tpm = self._tpm
        arriving = dump.tonnes

        for b in range(n_bands):
            lo, hi = int(b * band), int((b + 1) * band) if b < n_bands - 1 else len(moves)
            chunk = moves[lo:hi]
            if not chunk:
                continue
            layer.advance(dx_nd)
            out_t = 0.0
            by_src: dict[int, float] = {}
            for src, _, dh in chunk:
                t = dh * tpm
                out_t += t
                by_src[src] = by_src.get(src, 0.0) + t
            if out_t <= MIN_LOT_T:
                arriving = 0.0
                continue

            staying = max(0.0, arriving - out_t)
            base_frac = min(0.95, staying / (staying + out_t))
            phi_before = layer.mean_phi
            phi_dep, phi_move = layer.split_base(base_frac)
            # The solver's output is a redistribution, so what is applied to the ledger is the SHIFT
            # away from the layer's own mean, not an absolute composition. By construction
            # base_frac * d_dep + (1 - base_frac) * d_move is zero, so species mass is conserved, and
            # at Sr = 0 both shifts are exactly zero and no lot is touched.
            d_dep = phi_dep - phi_before
            d_move = phi_move - phi_before

            # What stopped in this band is fine-rich, so its coarse fraction falls by d_dep. The shift
            # is spread over the source columns in proportion to how much each of them shed, and only
            # down to the flowing depth: the layer is thin and the buried material took no part.
            if staying > MIN_LOT_T:
                for src, moved in by_src.items():
                    share = staying * (moved / out_t)
                    self._shift_top(src, min(share, self.col_t[src]), -d_dep)

            for src, dst, dh in chunk:
                t = dh * tpm
                if t <= MIN_LOT_T:
                    continue
                for lot in self._pop_top(src, t):
                    self._push(dst, Lot(lot.event_id, lot.tonnes, lot.grade_cu_pct,
                                        lot.grade_au_gpt,
                                        min(1.0, max(0.0, lot.coarse_frac - d_move)), lot.t_s))
                i, j = dst % pad.nx, dst // pad.nx
                if i in (0, pad.nx - 1) or j in (0, pad.ny - 1):
                    self.touched_boundary = True
            arriving = out_t

        return n_bands

    # ------------------------------------------------------------------ reclaim

    def reclaim(
        self,
        *,
        cut_id: int,
        t_s: float,
        target_t: float,
        method: str,
        front: int,
        picks: list[int] | None = None,
    ) -> tuple[ReclaimCut | None, int]:
        """Take one cut and return it with its provenance and the station the machine ended on.

        THE PARAMETERISATION, and why it is the physics rather than four arbitrary rules. A reclaim
        geometry is fixed by two numbers: what fraction of the face WIDTH the machine engages, and how
        far down the column it can REACH in one cut. Together they decide how many stacked layers end
        up in the cut, and the layer count is the dominant term in the variance reduction. A bridge or
        harrow reclaimer rakes the whole triangular section and therefore crosses every layer at that
        station, which is the entire reason bed blending works at all; a bucket wheel cuts a bench and
        reaches part way down; a loader takes a shallow bite. Nothing else about the machines matters
        to the grade of the cut.

        ================  =====  =====  ===========================================================
        method            width  depth  machine
        ================  =====  =====  ===========================================================
        ``fullface``      1.00   1.00   bridge or harrow reclaimer raking the full cross-section
        ``bucketwheel``   0.33   0.55   slewing bucket wheel cutting a bench
        ``end``           1.00   0.30   end reclaim taking the exposed end face
        ``loader``        3 cells 0.12  front-end loader biting the accessible face
        ================  =====  =====  ===========================================================

        The full-face rule takes a PROPORTIONAL share of every lot in the column rather than working
        from the top, because a rake engages the whole face at once. Every other method works from the
        top down, which is what makes it miss the buried layers.

        THE MACHINE WALKS. A shallow-reaching machine cannot fill a cut from one station, so it
        advances along the pile until the cut is complete, exactly as it would on a pad. Returning one
        undersized cut per station instead would have produced thousands of tiny cuts, which is not
        what the plant receives and which would have made the reclaimed stream look far more variable
        than it is purely as an artefact of the model's step size.
        """
        nx = self.pad.nx
        front = min(nx - 1, max(0, front))
        spec = RECLAIM_GEOMETRY[method]  # KeyError here is a programming error, not user input
        depth, proportional = spec["depth"], spec["proportional"]

        taken: list[Lot] = []
        got = 0.0
        stations = 0
        while got < target_t - MIN_LOT_T and stations < nx:
            cells = self._reclaim_cells(method, front, cut_id + stations)
            reach = sum(self.col_t[c] * depth for c in cells)
            if reach <= MIN_LOT_T:
                front = (front + 1) % nx
                stations += 1
                continue
            want = min(target_t - got, reach)
            if proportional:
                avail = sum(self.col_t[c] for c in cells)
                frac = want / avail
                for c in cells:
                    stack = self.stacks[c]
                    if not stack:
                        continue
                    keep: list[Lot] = []
                    removed = 0.0
                    for lot in stack:
                        part = lot.tonnes * frac
                        if part > MIN_LOT_T:
                            taken.append(Lot(lot.event_id, part, lot.grade_cu_pct, lot.grade_au_gpt,
                                             lot.coarse_frac, lot.t_s))
                            removed += part
                        rest = lot.tonnes - part
                        if rest > MIN_LOT_T:
                            keep.append(Lot(lot.event_id, rest, lot.grade_cu_pct, lot.grade_au_gpt,
                                            lot.coarse_frac, lot.t_s))
                    self.stacks[c] = keep
                    self.col_t[c] = max(0.0, self.col_t[c] - removed)
                    self.h[c] = self.col_t[c] / self._tpm
            else:
                per_cell = want / len(cells)
                for c in cells:
                    taken.extend(self._pop_top(c, min(per_cell, self.col_t[c] * depth)))
            new_got = sum(lot.tonnes for lot in taken)
            if new_got <= got + MIN_LOT_T:
                front = (front + 1) % nx
                stations += 1
                continue
            got = new_got
            if got < target_t - MIN_LOT_T:
                front = (front + 1) % nx
                stations += 1

        if got <= MIN_LOT_T:
            return None, front

        sources: dict[int, float] = {}
        g_cu = g_au = coarse = resid = 0.0
        for lot in taken:
            sources[lot.event_id] = sources.get(lot.event_id, 0.0) + lot.tonnes
            g_cu += lot.tonnes * lot.grade_cu_pct
            g_au += lot.tonnes * lot.grade_au_gpt
            coarse += lot.tonnes * lot.coarse_frac
            resid += lot.tonnes * (t_s - lot.t_s)
        for k in sources:
            sources[k] /= got

        self.reclaimed_t += got
        return ReclaimCut(
            cut_id=cut_id, t_s=t_s, tonnes=got,
            grade_cu_pct=g_cu / got, grade_au_gpt=g_au / got, coarse_frac=coarse / got,
            n_layers=len(sources), residence_s=resid / got, sources=sources,
        ), front

    def _reclaim_cells(self, method: str, front: int, salt: int) -> list[int]:
        """Which pad cells the machine engages at this station."""
        nx = self.pad.nx
        ny = self.pad.ny
        if method in ("fullface", "end"):
            return [j * nx + front for j in range(ny)]
        if method == "bucketwheel":
            lo = ny // 3
            return [j * nx + front for j in range(lo, min(ny, lo + max(1, ny // 3)))]
        if method == "loader":
            # scattered across the width rather than parked on the crest: a loader works wherever the
            # face is accessible, and always biting the deepest column would flatter the method
            step = max(1, ny // 3)
            js = [(salt * 7 + k * step) % ny for k in range(3)]
            return sorted({min(ny - 1, max(0, j)) * nx + front for j in js})
        raise ValueError(f"unknown reclaim method {method!r}")

    # ------------------------------------------------------------------ diagnostics

    def toe_apex_split(self) -> tuple[list[int], list[int]]:
        """Cells in the lowest and highest thirds of the occupied pad, by height.

        The segregation index and the toe-minus-apex grade delta are both differences between these
        groups. Defining them by height rather than by distance from a nominal centre keeps them
        meaningful for every stacking geometry, including the ones that build several crests.
        """
        occupied = [(self.h[c], c) for c in range(self.pad.n_cells) if self.h[c] > 1e-6]
        if len(occupied) < 6:
            return [], []
        occupied.sort()
        k = max(1, len(occupied) // 3)
        return [c for _, c in occupied[:k]], [c for _, c in occupied[-k:]]

    def apex_height_m(self) -> float:
        return max(self.h) if self.h else 0.0

    def steepest_slope_deg(self) -> float:
        """Steepest local slope actually standing, in degrees.

        Reported on the honesty panel next to the IMPOSED repose angle. If the relaxation were cutting
        its cascade short this number would exceed the imposed one, and a reader could see it rather
        than having to trust that it does not happen.
        """
        pad = self.pad
        worst = 0.0
        for j in range(pad.ny):
            base = j * pad.nx
            for i in range(pad.nx):
                c = base + i
                if i + 1 < pad.nx:
                    worst = max(worst, abs(self.h[c] - self.h[c + 1]))
                if j + 1 < pad.ny:
                    worst = max(worst, abs(self.h[c] - self.h[c + pad.nx]))
        return math.degrees(math.atan2(worst, pad.cell_m))
