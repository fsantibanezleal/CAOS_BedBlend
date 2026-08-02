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

WHAT IS AND IS NOT CLAIMED. The DIRECTION of every effect here is published and repeated across
independent sources. The functional forms are the simplest curves that reproduce those statements, and
they are calibrated so that the segregation index lands in the range a laboratory characterisation
test would report rather than being pinned to a single measured number. This is a defensible
operational model, not a validated constitutive one, and the product must say so. A DEM or the
laboratory test of Minerals Engineering would be the way to calibrate it properly, and that is
recorded as future work rather than quietly assumed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .material import Material, SizeSplit

# The published guidance that stockpile height be limited to 10 to 12 m because each extra metre
# increases segregation. Used as the reference height at which the model reports its nominal
# intensity, so the height dependence is anchored on a real operational threshold.
REFERENCE_DROP_M = 11.0

# Face angles below this behave as a slow, poorly segregating flow; above it the flow is fast and
# trajectory segregation dominates. The 35 to 40 against 30 to 35 split is the published boundary.
FAST_FLOW_ANGLE_DEG = 35.0


@dataclass(frozen=True)
class FaceSegregation:
    """How one cascading load ends up distributed down the face.

    ``coarse_profile`` and ``fine_profile`` are mass fractions in each down-face bin, from the crest
    at index 0 to the toe at the last index. They each sum to one, so the split between species is
    carried separately by the load's own size fractions and this object only describes WHERE each
    species went.

    ``overrun_fraction`` is the coarse mass that rolled BEYOND the toe of the face, which the source
    reports directly and which grows with drop height. It is reported separately because it leaves
    the face geometry entirely and lands on the floor in front of the pile.
    """

    coarse_profile: list[float]
    fine_profile: list[float]
    overrun_fraction: float
    intensity: float
    drop_m: float
    face_angle_deg: float

    @property
    def n_bins(self) -> int:
        return len(self.coarse_profile)

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

    OVERRUN. Part of the coarse "may also roll beyond the floor of the bench, especially at higher
    bench heights". It is taken off the coarse profile before normalisation, so the profiles still
    describe what stayed ON the face and the overrun is accounted separately.
    """
    n = max(n_bins, 2)
    g = intensity(drop_m, face_angle_deg, mat)

    # Bin centres from crest (0) to toe (1).
    s = [(k + 0.5) / n for k in range(n)]

    # Baseline is the measured mass distribution of the cascade itself, which already leans toward the
    # toe before any sorting: "aggregates more at the bottom of the dumping area ... and less near the
    # top crest". Sorting then acts on top of that.
    base = [0.35 + 0.65 * v for v in s]

    coarse = [b * (1.0 + 2.2 * g * (v - 0.5)) for b, v in zip(base, s, strict=True)]
    fine = [b * (1.0 - 1.6 * g * (v - 0.5)) for b, v in zip(base, s, strict=True)]
    coarse = [max(v, 0.0) for v in coarse]
    fine = [max(v, 0.0) for v in fine]

    # Overrun grows with intensity and with drop, and is bounded: even a tall face does not throw most
    # of its coarse off the toe. The cap is an operational judgement, marked as such.
    overrun = min(0.25, 0.30 * g * (1.0 - math.exp(-drop_m / (2.0 * REFERENCE_DROP_M))))

    cs, fs = sum(coarse), sum(fine)
    coarse = [v / cs * (1.0 - overrun) for v in coarse] if cs > 0 else [0.0] * n
    fine = [v / fs for v in fine] if fs > 0 else [0.0] * n

    return FaceSegregation(
        coarse_profile=coarse,
        fine_profile=fine,
        overrun_fraction=overrun,
        intensity=g,
        drop_m=drop_m,
        face_angle_deg=face_angle_deg,
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
