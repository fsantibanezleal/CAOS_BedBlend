"""Size segregation down a dumped face: the coarse runs to the toe.

THE ENGINE HAD A SEGREGATION SOLVER AND NEVER APPLIED IT. ``segregation`` integrates Gray and
Thornton's kinetic sieving along a flowing layer, which is the right physics for what happens inside
an avalanche. But in the previous product nothing ever formed a face, so there was no avalanche to
integrate along and the solver had nothing to separate. This module is the coupling: it takes a load
cascading over a crest and returns how its coarse and fine species end up distributed down the face.

WHAT THE SOURCES SAY, and all of it points the same way.

  * "This cascade of material typically aggregates more at the bottom of the dumping area under
    normal conditions and less near the top crest of the dump. ... Round and large material may also
    roll beyond the floor of the bench, especially at higher bench heights." (Young and Rogers,
    Minerals 2021, 11, 636, section 3.3.)
  * "coarser particles hit the front face of the stockpile with greater momentum and roll down the
    outer edge of the pile, creating an accumulation of particles at the pile's bottom edge or toe,
    resulting in a segregated stockpile with coarse particles settled at the toes and fine particles
    in the center portion of the pile."
  * "The feeding height was found to influence segregation", and conical stockpile height "should be
    limited to 10-12 m maximum, as each additional meter of height increases percolation segregation."
  * "a segregated pile often has a slightly larger angle of repose at the top compared to the base of
    the pile", because the top is left finer once the coarse has run off.
  * Steeper faces at 35 to 40 degrees "create faster material flow down the face, increasing
    trajectory segregation".

SO THREE THINGS DRIVE IT, and all three are already quantities this engine has: the drop height, the
face angle, and the material's own size split. None of them is a free knob.

WHAT IS AND IS NOT CLAIMED, AND THIS PARAGRAPH USED TO BE WRONG. It said the functional forms were
"the simplest curves that reproduce those statements", and that was true: this module fitted three
curves with six constants and never touched ``segregation``, the module next to it that integrates
Gray and Thornton's kinetic sieving. The engine documented a validated continuum model, rated it
SOTA, and ran an operational stand-in. The directions were right, which is exactly why it survived.

IT NOW SOLVES THE EQUATION. ``segregate_face`` marches a real ``FlowingLayer`` down the face: the
conservation law ``d(phi)/dx + d(F)/dz = 0`` with ``F(phi) = -Sr phi (1 - phi)``, a Godunov flux, CFL
sub-stepping, and deposition by ``split_base``, which conserves species mass exactly rather than
approximately. THE SIZE DISTRIBUTION AT EVERY POINT ON THE FACE COMES FROM THAT SOLVER AND FROM
NOTHING ELSE. Two quantities are still operational observations, both published, both labelled, and
neither of them touches the size distribution:

  * WHERE THE MASS LANDS down the face, "aggregates more at the bottom ... and less near the top
    crest", which is a statement about the cascade's geometry and not about sieving;
  * HOW MUCH OVERRUNS the toe, "may also roll beyond the floor of the bench", which is ballistic
    trajectory segregation, a different mechanism that this solver does not model. Its COMPOSITION,
    though, comes from the solver: what overruns is the material still travelling at the toe, and the
    solver says what that is made of.

WHAT THE MECHANICS THEN SAY, INCLUDING WHERE IT DISAGREES WITH THE OLD CURVES. The layer's velocity
comes from the depth-averaged momentum balance on a slope, ``U = sqrt(2 g (sin(t) - mu cos(t)) L)``
with ``mu`` the tangent of the DYNAMIC friction angle; its thickness from flux conservation,
``H = Q / U``, floored at a few particle diameters; and the percolation velocity scales on the shear
rate, ``q = kappa (U/H) d``. The segregation number is then

    Sr = q L / (H U) = kappa d L / H^2

and note that U has CANCELLED. How fast the layer runs does not change how much it sieves per metre
of slope: a slower layer takes longer over the same path and sorts by the same amount.

WHICH REGIME ACTUALLY BINDS, measured rather than assumed. For run-of-mine rock at a 120 mm d50 the
flux-limited thickness ``Q/U`` is 0.09 to 0.35 m across every drop and angle the product runs, and the
grain floor is 0.60 m, so the layer is GRAIN-LIMITED in every case and never flux-limited. H is
therefore constant and

    Sr = kappa d L / h_min^2,      L = drop / sin(t)

so kinetic sieving RISES with the drop height, which is the published direction, and FALLS GENTLY WITH
THE FACE ANGLE because a steeper face is a SHORTER path from crest to toe.

THAT LAST ONE CONTRADICTS A SOURCE, AND THE CONTRADICTION IS THE POINT. Steeper faces are reported to
"create faster material flow down the face, increasing trajectory segregation", and the curve this
module used to fit duly made its index rise with angle. But trajectory segregation is BALLISTIC, a
different mechanism from kinetic sieving, and Gray and Thornton's equation does not contain it. Wiring
the real solver separated the two mechanisms that the fitted curve had merged. So the model now says:
on-face sieving weakens slightly with angle, while the material thrown clear of the toe, which is the
trajectory term, grows with angle, and it is almost pure coarse. Both are reported, neither is hidden
inside a single index, and a reader can check each against the source it came from.

It also predicts something the fitted curves could not: a face standing below the material's dynamic
friction angle does not avalanche, so it does not sort, and the model now says so instead of
decorating a stable slope with a gradient.

WHAT IS STILL ANCHORED RATHER THAN MEASURED. One number: ``PERCOLATION_COEFFICIENT``, the ratio of the
percolation velocity to the shear rate times the particle diameter. It is set so that Sr for a
reference dump lands inside the range of the source's own worked examples, and it is precisely the
number the DEM calibration lane exists to replace. A DEM run or the laboratory characterisation test
would pin it; neither has been run for this release, and that is recorded rather than assumed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .material import Material, SizeSplit
from .segregation import NZ_DEFAULT, FlowingLayer, segregation_number

# The published guidance that stockpile height be limited to 10 to 12 m because each extra metre
# increases segregation. Used as the reference height at which the model reports its nominal
# intensity, so the height dependence is anchored on a real operational threshold.
REFERENCE_DROP_M = 11.0

# Face angles below this behave as a slow, poorly segregating flow; above it the flow is fast and
# trajectory segregation dominates. The 35 to 40 against 30 to 35 split is the published boundary.
FAST_FLOW_ANGLE_DEG = 35.0

GRAVITY_M_S2 = 9.81

# THE ONE ANCHORED NUMBER. kappa in q = kappa * shear_rate * d, the percolation velocity of the fines
# through the sheared layer. Set so that Sr for a reference dump (an 11 m face at 37 degrees in the
# default material) comes out around 1.8, inside the range of the worked examples in the source. This
# is the parameter the DEM calibration lane exists to measure, and until that lane is run it is an
# anchor and is reported as one. Nothing else in this module is fitted to a segregation measurement.
PERCOLATION_COEFFICIENT = 0.30

# The flowing layer cannot be thinner than a few grains however fast it goes: below that there is no
# layer to sieve through and the continuum description stops meaning anything. In particle diameters.
LAYER_MIN_DIAMETERS = 5.0

# Volumetric flux per unit width of a load cascading over the crest, in square metres per second.
# A haul truck body empties in about ten seconds across about ten metres of crest, which for a
# hundred cubic metre load is of order one. It sets the flowing layer thickness through H = Q / U.
CASCADE_FLUX_M2_S = 1.0

# Granular flow starts at a steeper angle than it stops at, so the DYNAMIC friction angle that governs
# an avalanche already in motion sits below the static angle of repose. A few degrees is the published
# width of that hysteresis, and using the material's own repose angle to derive it means the flow
# model takes no free parameter of its own.
FLOW_HYSTERESIS_DEG = 4.0


@dataclass(frozen=True)
class Avalanche:
    """The flowing layer's own state, which is what the solver actually needs.

    Exposed as a value rather than kept inside ``segregate_face`` because these are the physical
    quantities a reader can check against their own operation: how long the run is, how thick and how
    fast the layer is, and what segregation number those imply. ``segregation`` exposes
    ``segregation_number`` for exactly this reason, and this is the object that carries the answer.

    ``flows`` is False when the face stands below the material's dynamic friction angle. Such a face
    does not avalanche, so nothing sieves, and the honest output is no sorting at all.
    """

    path_m: float
    layer_h_m: float
    u_ms: float
    q_ms: float
    sr: float
    flows: bool


def avalanche_state(drop_m: float, face_angle_deg: float, mat: Material) -> Avalanche:
    """Solve the flowing layer's geometry and speed, and from them its segregation number.

    Depth-averaged momentum balance on a slope for a layer starting from rest at the crest,

        a = g (sin(t) - mu cos(t)),      U = sqrt(2 a L),      L = drop / sin(t)

    with ``mu`` the tangent of the DYNAMIC friction angle, taken as the material's repose angle less
    the start-stop hysteresis. Mass flux conservation then fixes the layer thickness, ``H = Q / U``,
    floored at a few particle diameters because a layer thinner than its own grains is not a layer.
    The percolation velocity scales on the shear rate, ``q = kappa (U / H) d``, and the segregation
    number is the published ratio ``Sr = q L / (H U)``.
    """
    drop = max(drop_m, 0.0)
    theta = math.radians(min(max(face_angle_deg, 0.0), 89.0))
    sin_t, cos_t = math.sin(theta), math.cos(theta)
    d_m = max(mat.d50_mm, 1e-6) / 1000.0
    h_min = LAYER_MIN_DIAMETERS * d_m

    mu = math.tan(math.radians(max(mat.repose_dry_deg - FLOW_HYSTERESIS_DEG, 1.0)))
    accel = GRAVITY_M_S2 * (sin_t - mu * cos_t)
    if drop <= 0.0 or sin_t <= 0.0 or accel <= 0.0:
        # A flat tip has no face to run down, and a face below the dynamic friction angle does not
        # run at all. Either way there is no avalanche and therefore no kinetic sieving.
        return Avalanche(0.0, h_min, 0.0, 0.0, 0.0, flows=False)

    path_m = drop / sin_t
    u_ms = math.sqrt(2.0 * accel * path_m)
    layer_h_m = max(CASCADE_FLUX_M2_S / u_ms, h_min)
    q_ms = PERCOLATION_COEFFICIENT * (u_ms / layer_h_m) * d_m
    return Avalanche(
        path_m=path_m,
        layer_h_m=layer_h_m,
        u_ms=u_ms,
        q_ms=q_ms,
        sr=segregation_number(q_ms, path_m, layer_h_m, u_ms),
        flows=True,
    )


@dataclass(frozen=True)
class FaceSegregation:
    """How one cascading load ends up distributed down the face.

    ``coarse_profile`` and ``fine_profile`` are, for each down-face bin from the crest at index 0 to
    the toe at the last index, the share of THAT SPECIES in the load which came to rest there. Each
    sums to the share of its species that stayed on the face, so the two sums differ, and the
    difference is itself a result: coarse overruns the toe preferentially, so its profile sums lower.

    ``overrun_fraction`` is the total mass that ran BEYOND the toe and landed on the floor in front of
    the pile, and ``overrun_coarse_fraction`` is what that material is made of. The source reports the
    overrun directly and reports that it is the coarse that does it; the magnitude here is the
    published operational observation and the composition is the solver's answer, since what overruns
    is whatever is still travelling in the layer when it reaches the toe.

    ``avalanche`` carries the flowing layer the solver actually marched, so the segregation number and
    the physical quantities behind it can be presented rather than asserted.
    """

    coarse_profile: list[float]
    fine_profile: list[float]
    overrun_fraction: float
    intensity: float
    drop_m: float
    face_angle_deg: float
    overrun_coarse_fraction: float = 0.0
    avalanche: Avalanche | None = None

    @property
    def n_bins(self) -> int:
        return len(self.coarse_profile)

    @property
    def sr(self) -> float:
        """The segregation number the face was solved at. Zero means the face did not avalanche."""
        return self.avalanche.sr if self.avalanche else 0.0

    def coarse_fraction_at(self, split: SizeSplit, k: int) -> float:
        """Local coarse fraction in bin ``k``, which is what the ledger records per cell.

        This is the number a reader cares about: not "where did the coarse go" but "what is the size
        composition of the material sitting at this point on the face".
        """
        c = split.coarse * self.coarse_profile[k]
        f = split.fine * self.fine_profile[k]
        return c / (c + f) if (c + f) > 0 else 0.0


def intensity(drop_m: float, face_angle_deg: float, mat: Material) -> float:
    """How strongly this cascade segregates, on a zero to one scale.

    Three published drivers, combined multiplicatively because each can independently suppress the
    effect: a load that barely drops, or one that creeps down a shallow face, or one that is all the
    same size, does not segregate whichever of the other two applies.

      HEIGHT     "each additional meter of height increases percolation segregation", anchored on the
                 10 to 12 m operational limit.
      FACE ANGLE steeper faces "create faster material flow down the face, increasing trajectory
                 segregation".
      SIZE SPREAD a single-sized material cannot segregate at all, so the term vanishes as the split
                 approaches all-coarse or all-fine.
    """
    h = 1.0 - math.exp(-max(drop_m, 0.0) / REFERENCE_DROP_M)

    # Rises through the published 30-to-40 degree window and saturates beyond it.
    a = min(max((face_angle_deg - 28.0) / (FAST_FLOW_ANGLE_DEG + 5.0 - 28.0), 0.0), 1.0)

    # Maximal at an even split, zero when the material is all one species. 4c(1-c) is the simplest
    # function with exactly that shape.
    c = min(max(mat.coarse_fraction, 0.0), 1.0)
    s = 4.0 * c * (1.0 - c)

    return h * a * s


def segregate_face(
    *,
    drop_m: float,
    face_angle_deg: float,
    mat: Material,
    n_bins: int = 12,
) -> FaceSegregation:
    """Distribute a cascading load's two species down the face.

    Coarse mass is pushed toward the toe and fine mass toward the crest, in proportion to the
    intensity. At zero intensity both come out uniform, which is the correct degenerate case: a load
    tipped on flat ground, or one of a single size, does not sort itself.

    HOW IT IS SOLVED. A ``FlowingLayer`` is started at the crest holding the load's own fine fraction
    uniformly through its depth. It is marched down the face in ``n_bins`` steps of the
    non-dimensional downslope coordinate, and at each step the bottom of the layer is deposited by
    ``split_base``. Kinetic sieving drives fines to the BASE of a flowing layer, so what is laid down
    early is fine-rich and what keeps travelling is coarse-rich; the coarse therefore arrives at the
    toe. That is the published direction, and here it is a consequence of the flux ``F(phi) = -Sr phi
    (1 - phi)`` rather than an assumption.

    HOW MUCH IS LAID DOWN AT EACH STEP is not solved, it is observed: "this cascade of material
    typically aggregates more at the bottom of the dumping area ... and less near the top crest". That
    published mass distribution is imposed, the sieving is not, and the two are kept separate on
    purpose so that the claim about each can be checked on its own.

    OVERRUN. Part of the material "may also roll beyond the floor of the bench, especially at higher
    bench heights". That is ballistic trajectory segregation and this solver does not model it, so its
    MAGNITUDE stays an operational term driven by the published drivers. Its COMPOSITION is the
    solver's: what overruns is whatever is still in the layer at the toe.
    """
    n = max(n_bins, 2)
    g = intensity(drop_m, face_angle_deg, mat)
    av = avalanche_state(drop_m, face_angle_deg, mat)
    split = SizeSplit.of(mat.coarse_fraction)

    # Bin centres from crest (0) to toe (1).
    s = [(k + 0.5) / n for k in range(n)]

    # The published mass distribution of the cascade: it leans toward the toe before any sorting.
    w = [0.35 + 0.65 * v for v in s]
    w_sum = sum(w)
    w = [v / w_sum for v in w]

    # Overrun grows with the published drivers and is bounded: even a tall face does not throw most of
    # its load off the toe. The cap is an operational judgement, marked as such. Gated on the face
    # actually avalanching, because nothing can roll past the toe of a slope nothing is running down.
    overrun = (
        min(0.25, 0.30 * g * (1.0 - math.exp(-drop_m / (2.0 * REFERENCE_DROP_M))))
        if av.flows else 0.0
    )

    # THE MARCH. phi is the FINE fraction, index 0 at the base of the layer where the fines collect.
    layer = FlowingLayer(phi0=split.fine, sr=av.sr, nz=NZ_DEFAULT)
    dx_nd = 1.0 / n            # Sr already carries the path length, so the run is 0 to 1

    coarse_mass = [0.0] * n
    fine_mass = [0.0] * n
    remaining = 1.0            # mass still travelling, as a fraction of the load
    for k in range(n):
        layer.advance(dx_nd)
        deposit = w[k] * (1.0 - overrun)
        if deposit <= 0.0 or remaining <= 1e-12:
            continue
        phi_dep, _phi_rest = layer.split_base(min(1.0, deposit / remaining))
        fine_mass[k] = deposit * phi_dep
        coarse_mass[k] = deposit * (1.0 - phi_dep)
        remaining -= deposit

    # Whatever is still travelling at the toe is what leaves the face, and the solver says what it is.
    overrun_phi = layer.mean_phi if av.flows else split.fine

    # Normalise each species by how much of it the load held, so that
    # ``split.coarse * coarse_profile[k]`` is the coarse MASS in bin k and the local coarse fraction
    # follows directly. Species mass is conserved by the march, so each profile sums to the share of
    # its species that stayed on the face.
    c_tot = max(split.coarse, 1e-12)
    f_tot = max(split.fine, 1e-12)
    coarse = [v / c_tot for v in coarse_mass]
    fine = [v / f_tot for v in fine_mass]

    return FaceSegregation(
        coarse_profile=coarse,
        fine_profile=fine,
        overrun_fraction=overrun,
        intensity=g,
        drop_m=drop_m,
        face_angle_deg=face_angle_deg,
        overrun_coarse_fraction=1.0 - overrun_phi,
        avalanche=av,
    )


def segregation_index(seg: FaceSegregation, split: SizeSplit) -> float:
    """A single number for how sorted the face is, comparable between runs.

    Defined as the difference in local coarse fraction between the toe half and the crest half of the
    face. Zero means no sorting; positive means coarse at the toe, which is the direction every source
    reports. Negative would mean coarse at the crest, which would indicate the model had been wired up
    backwards, so the sign is itself a test.
    """
    n = seg.n_bins
    half = n // 2
    top = [seg.coarse_fraction_at(split, k) for k in range(half)]
    bot = [seg.coarse_fraction_at(split, k) for k in range(half, n)]
    if not top or not bot:
        return 0.0
    return sum(bot) / len(bot) - sum(top) / len(top)


def total_segregation_index(seg: FaceSegregation, split: SizeSplit) -> float:
    """Sorting of the whole dumped load, counting what ran past the toe as toe material.

    ``segregation_index`` measures the face and only the face, which is the right answer to "how
    sorted is the slope I am looking at" and the WRONG answer to "did this dump segregate". A taller
    face throws more material clear of the toe, that material is almost pure coarse, and removing it
    from the face makes the ON-FACE index fall even as the load as a whole ends up more sorted. The
    two indices diverging above about fifteen metres of drop is not a defect, it is the overrun, and
    reporting only the first would have made a taller bench look like it sorted less.

    The overrun lands on the floor in front of the pile, so it belongs to the toe. Mass-weighted,
    because the bins do not carry equal mass.
    """
    n = seg.n_bins
    half = n // 2
    if half == 0:
        return 0.0

    def mass(k: int) -> tuple[float, float]:
        return split.coarse * seg.coarse_profile[k], split.fine * seg.fine_profile[k]

    def frac(rng, extra_c: float = 0.0, extra_f: float = 0.0) -> float:
        c = sum(mass(k)[0] for k in rng) + extra_c
        f = sum(mass(k)[1] for k in rng) + extra_f
        return c / (c + f) if (c + f) > 0 else 0.0

    ov = seg.overrun_fraction
    return (
        frac(range(half, n), ov * seg.overrun_coarse_fraction, ov * (1.0 - seg.overrun_coarse_fraction))
        - frac(range(half))
    )


def apparent_repose_deg(seg: FaceSegregation, split: SizeSplit, mat: Material) -> tuple[float, float]:
    """``(angle near the crest, angle near the toe)`` for a segregated face.

    "a segregated pile often has a slightly larger angle of repose at the top compared to the base of
    the pile". That falls out of the sorting rather than being imposed: the crest keeps the fines once
    the coarse has run off, and the two species do not stand at the same angle. Whether the top comes
    out steeper depends on which species stands steeper, so this reports both ends and lets the caller
    compare them instead of asserting a direction the material may not have.
    """
    n = seg.n_bins
    half = max(1, n // 3)
    top_c = sum(seg.coarse_fraction_at(split, k) for k in range(half)) / half
    bot_c = sum(seg.coarse_fraction_at(split, k) for k in range(n - half, n)) / half
    return (
        SizeSplit.of(top_c).blended_repose_deg(mat),
        SizeSplit.of(bot_c).blended_repose_deg(mat),
    )
