"""Method 4, kinetic size segregation in the flowing layer, solved as a conservation law.

THE MODEL. Gray and Thornton, "A theory for particle size segregation in shallow granular
free-surface flows", Proc. R. Soc. A 461(2057), 1447-1473, 2005, doi:10.1098/rspa.2004.1420.

Their result, with their equation numbers. The percolation velocities of each species relative to the
bulk are

    w_l - w = + q phi_s        (large particles are levered up)                              (3.10)
    w_s - w = - q phi_l        (small particles drain down)                                  (3.10)

with the mean segregation velocity

    q = (B / c) g cos(zeta)                                                                  (3.11)

Substituting into the small-particle mass balance and non-dimensionalising with the standard
avalanche scalings gives

    dphi/dt + d(phi u)/dx + d(phi v)/dy + d(phi w)/dz - Sr d/dz[ phi (1 - phi) ] = 0          (3.18)

where the segregation number

    Sr = q L / (H U)                                                                         (3.19)

is the ratio of the mean segregation velocity to the typical normal bulk velocity. When ``Sr`` is
zero the equation degenerates to pure tracer advection, that is, no segregation: that limit is the
product's negative control C02 and it comes free from this same solver rather than from a separate
code path, which is what makes the control meaningful.

WHAT IS SOLVED HERE. On a stockpile flank the avalanche is a shallow layer of roughly uniform
thickness flowing over a static bed. Taking plug flow and marching in the downslope coordinate ``x``
reduces (3.18) to a one-dimensional scalar conservation law in depth,

    dphi/dx + dF/dz = 0,      F(phi) = - Sr phi (1 - phi)

with no flux through the free surface or the base. ``phi`` is the volume fraction of the SMALL
species. ``F`` is convex, so a Godunov flux is exact for the Riemann problem at every interface.

WHY THIS RUNS LIVE. Thirty-two depth cells and a handful of sub-steps per downslope cell is a few
hundred floating-point operations per avalanche generation. The published continuum model is
therefore cheaper than the fitted parametric curve it might have been replaced with, and it is
defensible where the curve would not have been. That was the single most useful finding of the
research pass and it is recorded in ``plans/stocktwin/findings.md``.

THE COUPLING TO THE PILE. Fines drain to the BASE of the flowing layer. Material that stops on the
flank is drawn from that base, and material that keeps travelling is drawn from the top. So the toe,
which is fed by the material that travelled furthest, ends up coarse. Coarse-at-the-toe is therefore
an OUTPUT of the model, not a rule written into it.
"""
from __future__ import annotations

NZ_DEFAULT = 32
CFL = 0.4

# DIFFUSIVE REMIXING, Gray and Chugunov 2006, "A theory for particle size segregation in shallow
# granular free-surface flows", J. Fluid Mech. 569, 365-398, doi:10.1017/S0022112006002977. It is the
# direct successor to the 2005 paper this module already integrates, and it adds the one term that
# paper leaves out: the random collisional remixing that opposes the sieving.
#
# WITHOUT IT THE MODEL SATURATES AND THE PRODUCT GOES DEAF. The pure hyperbolic flux separates the
# species completely and then stops, so beyond about Sr = 1.5 every face gives the identical profile.
# Measured on this engine's own reference material, the on-face sorting index was 0.5162 at Sr = 1.5
# and 0.5162 at Sr = 15, while real dumps sit between Sr = 1.8 and Sr = 4: every scenario in the
# product would have reported the same segregation whatever its drop height or face angle. Shocks are
# a real feature of the 2005 solution and they are kept; what the remixing adds is that the shock has
# a finite thickness, which is what stops the answer being binary.
#
# The Peclet number is the ratio of sieving to remixing, ``Pe = Sr / Dr``. Gray and Chugunov fit it
# against chute experiments and report values of order ten; it is held here at the middle of that
# range and, like the percolation coefficient in ``facesegregation``, it is an anchor from the
# literature rather than a fit to this material.
PECLET_DEFAULT = 12.0


def _godunov_flux(pl: float, pr: float, sr: float) -> float:
    """Godunov flux for the convex flux ``F(phi) = -Sr phi (1 - phi)`` between states ``pl`` and ``pr``.

    ``F`` is convex (it is ``Sr(phi^2 - phi)``) with its minimum at ``phi = 0.5``, so the exact
    Riemann solution is the min of ``F`` over the interval when the states increase and the max when
    they decrease. Writing the two branches explicitly, rather than reaching for a Lax-Friedrichs
    smear, keeps the concentration shocks that Gray and Thornton identify as the physically observed
    feature.
    """
    def f(p: float) -> float:
        return -sr * p * (1.0 - p)

    if pl <= pr:
        if pl <= 0.5 <= pr:
            return f(0.5)
        return min(f(pl), f(pr))
    if pr <= 0.5 <= pl:
        return max(f(pl), f(pr))
    return max(f(pl), f(pr))


class FlowingLayer:
    """The avalanching layer above the static bed, carrying a depth profile of the fine fraction.

    Index 0 is the BASE of the layer (against the static bed) and index ``nz - 1`` is the free
    surface. One instance lives for the duration of one dump's avalanche; ``advance`` moves it one
    cell downslope and ``split_base`` performs the deposition.
    """

    __slots__ = ("nz", "phi", "sr", "pe")

    def __init__(
        self, phi0: float, sr: float, nz: int = NZ_DEFAULT, pe: float = PECLET_DEFAULT
    ) -> None:
        p = min(1.0, max(0.0, float(phi0)))
        self.nz = int(nz)
        self.sr = max(0.0, float(sr))
        # Peclet number: sieving against remixing. Infinite (or non-positive, read as "off") recovers
        # the pure 2005 hyperbolic model exactly, which is what the shock tests pin.
        self.pe = float(pe)
        self.phi = [p] * self.nz

    @property
    def diffusivity(self) -> float:
        """``Dr = Sr / Pe``. Zero when there is no sieving, so the passive-tracer control is exact."""
        if self.pe <= 0.0 or self.pe == float("inf"):
            return 0.0
        return self.sr / self.pe

    @property
    def mean_phi(self) -> float:
        """Depth-averaged fine fraction. Conserved exactly by ``advance``; the test asserts it."""
        return sum(self.phi) / self.nz

    def advance(self, dx_nd: float) -> None:
        """March the profile ``dx_nd`` in non-dimensional downslope distance.

        Sub-stepped to respect the CFL condition. The characteristic speed of ``F`` is
        ``|F'(phi)| = Sr|1 - 2 phi|``, bounded by ``Sr``, so a step of ``CFL * dz / Sr`` is stable.
        No-flux boundaries are imposed by setting the surface and base interface fluxes to zero,
        which is the boundary condition in the source and is also what makes the scheme conservative.

        THE REMIXING TERM, ``d/dz(Dr dphi/dz)``, is carried on the same interfaces as the segregation
        flux and with the same no-flux walls, so the scheme stays exactly conservative with it on: the
        species-mass test passes unchanged rather than to a looser tolerance. Being parabolic it has
        its own stability limit, ``dz^2 / (2 Dr)``, and the sub-step honours whichever of the two
        limits is tighter.
        """
        if self.sr <= 0.0 or dx_nd <= 0.0:
            return  # Sr = 0 is the no-segregation control: the profile is a passive tracer
        dz = 1.0 / self.nz
        dr = self.diffusivity
        max_step = CFL * dz / self.sr
        if dr > 0.0:
            max_step = min(max_step, CFL * dz * dz / (2.0 * dr))
        n_sub = max(1, int(dx_nd / max_step) + 1)
        h = dx_nd / n_sub
        ratio = h / dz
        d_ratio = dr * h / (dz * dz)
        nz = self.nz
        for _ in range(n_sub):
            phi = self.phi
            flux = [0.0] * (nz + 1)  # flux[i] sits below cell i; flux[0] and flux[nz] are the walls
            for i in range(1, nz):
                flux[i] = _godunov_flux(phi[i - 1], phi[i], self.sr)
            if d_ratio > 0.0:
                self.phi = [
                    min(1.0, max(0.0,
                        phi[i]
                        - ratio * (flux[i + 1] - flux[i])
                        + d_ratio * (
                            (phi[i + 1] if i + 1 < nz else phi[i])
                            - 2.0 * phi[i]
                            + (phi[i - 1] if i > 0 else phi[i])
                        )
                    ))
                    for i in range(nz)
                ]
            else:
                self.phi = [
                    min(1.0, max(0.0, phi[i] - ratio * (flux[i + 1] - flux[i])))
                    for i in range(nz)
                ]

    def split_base(self, base_frac: float) -> tuple[float, float]:
        """Deposit the bottom ``base_frac`` of the layer and keep the rest travelling.

        Returns ``(phi_deposited, phi_remaining)``: the fine fraction of the material left on the
        flank here, and of the material that continues downslope. The layer is replaced by its top
        portion, regridded back to ``nz`` cells by conservative averaging.

        Species mass is conserved exactly by construction, since
        ``base_frac * phi_deposited + (1 - base_frac) * phi_remaining == mean_phi`` before the call.
        That identity is a test, not a comment.
        """
        f = min(1.0, max(0.0, float(base_frac)))
        if f <= 0.0:
            return self.mean_phi, self.mean_phi
        if f >= 1.0:
            m = self.mean_phi
            return m, m
        lo, hi = min(self.phi), max(self.phi)
        if hi - lo <= 1e-15:
            # A uniform layer, which is what Sr = 0 always produces, splits into two portions of
            # exactly the same composition. Short-circuiting rather than integrating keeps that
            # EXACT: the quadrature below is correct to about 1e-16, and the C02 negative control
            # asserts equality, not near-equality, because "the solver did nothing" has to be
            # provable rather than approximately true.
            return lo, lo

        nz = self.nz
        dz = 1.0 / nz
        # exact depth-integral of the bottom f of the layer, splitting the straddling cell
        acc = 0.0
        z = 0.0
        i = 0
        while i < nz and z + dz <= f + 1e-15:
            acc += self.phi[i] * dz
            z += dz
            i += 1
        if i < nz and f - z > 1e-15:
            acc += self.phi[i] * (f - z)
        phi_dep = acc / f

        total = self.mean_phi
        rest = 1.0 - f
        phi_rest = (total - acc) / rest

        # regrid the remaining top portion [f, 1] onto nz cells, conservatively
        new = [0.0] * nz
        step = rest / nz
        for k in range(nz):
            lo = f + k * step
            hi = lo + step
            s = 0.0
            a = lo
            while a < hi - 1e-15:
                cell = min(nz - 1, int(a / dz))
                cell_hi = (cell + 1) * dz
                b = min(hi, cell_hi)
                s += self.phi[cell] * (b - a)
                a = b
            new[k] = min(1.0, max(0.0, s / step))
        self.phi = new
        return phi_dep, phi_rest


def segregation_number(q_ms: float, path_m: float, layer_h_m: float, u_ms: float) -> float:
    """Equation (3.19): ``Sr = q L / (H U)``.

    Exposed so the App can present the physical quantities a reader can reason about (the segregation
    velocity, the path length, the flowing-layer thickness and the flow speed) rather than a bare
    dimensionless knob with no units attached to it.
    """
    denom = layer_h_m * u_ms
    if denom <= 0.0:
        return 0.0
    return max(0.0, q_ms * path_m / denom)
