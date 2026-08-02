"""Material properties: density through the handling chain, moisture, and size.

WHY A SEPARATE MODULE. Three quantities were being carried as single constants that are in fact
different numbers at different points in the process, and treating them as one is a real modelling
error rather than a simplification:

  * DENSITY changes three times. Rock in the ground is dense; blasted and loaded it SWELLS; placed and
    then trafficked it COMPACTS again. Using one figure means tonnage and volume cannot both be right.
  * THE ANGLE OF REPOSE IS NOT A CONSTANT of the ore. It moves with moisture and with fines content,
    and the product was imposing a single value as though it were a material constant.
  * SIZE is what segregates. A model with one grade per load and no size distribution cannot show
    segregation at all, whatever solver it runs, because there is nothing to separate.

THE NUMBERS, and where each comes from.

Swell. "When mined, in situ material will swell from 10 to 60 percent depending on the type of
material and fracture frequency. In hard rock operations, the percent swell is commonly between 30 and
45 percent" (Atlantech, open-cut mining swell, 2026; consistent with the NRC bulking-factor
compilation ML080700314).

Compaction. "Typical compaction percentages range from 5 to 15 percent", and it is driven by traffic:
field trials reducing the dumping layer from 5 m to 2 m "combined with 20 to 30 passes of a 20-ton
compactor or heavy dump truck, effectively increased the density and strength of the waste dump
material". Access roads are deliberately "routed over existing waste to add both weight and a
vibratory compaction from trucks and other equipment".

Moisture and repose. Steeper repose angles of 35 to 40 degrees "create faster material flow down the
face, increasing trajectory segregation", while flatter angles of 30 to 35 degrees "can be achieved by
managing material moisture and fines content". Moisture raises the angle through capillary cohesion up
to a point and then collapses it when the material becomes saturated and starts to flow, which is why
the relationship here is not monotonic.

WHAT IS NOT CLAIMED. These are published operational bands, not a constitutive model. Every figure is
a parameter with its source in the docstring, and the product must describe them as bands rather than
as constants. Anything genuinely uncertain is marked in the field comment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Hard-rock swell, as a fraction of in-situ volume. The wider 10 to 60 percent band covers soils and
# weak rock; 30 to 45 is the hard-rock case this engine is built for.
SWELL_HARD_ROCK = (0.30, 0.45)
SWELL_ALL_MATERIALS = (0.10, 0.60)

# Compaction achievable under traffic, as a fraction of loose volume.
COMPACTION_BAND = (0.05, 0.15)

# Passes of a heavy truck or compactor over a layer to reach most of that compaction. The field trial
# quotes 20 to 30 passes on a 2 m layer.
PASSES_FOR_FULL_COMPACTION = 25.0


@dataclass(frozen=True)
class Material:
    """One ore type, with the properties that actually change the geometry.

    ``d50_mm`` and ``coarse_fraction`` are what segregation acts on. A load is not a single size: it
    is a distribution, and the cascade sorts it. Carrying only a mean size would make the segregation
    solver decorative.
    """

    name: str = "ROM ore"
    # In-situ (solid) density before blasting.
    insitu_density_t_m3: float = 2.70
    # Fraction by which the rock swells on being blasted and loaded.
    swell: float = 0.38
    # Achievable compaction under traffic, as a fraction of loose volume.
    max_compaction: float = 0.10
    # Dry angle of repose of the bulk material.
    repose_dry_deg: float = 37.0
    # Gravimetric moisture, as a fraction of dry mass.
    moisture: float = 0.03
    # Moisture above which the material starts behaving as a slurry and the angle collapses.
    saturation_moisture: float = 0.20
    # Size, as a two-species split. The coarse species is what runs to the toe.
    d50_mm: float = 120.0
    coarse_fraction: float = 0.35
    # Repose angle of the coarse species on its own. Coarse, angular rock stands steeper than fines,
    # and the DIFFERENCE between the two is what drives stratification.
    repose_coarse_deg: float = 40.0
    repose_fine_deg: float = 34.0

    @property
    def loose_density_t_m3(self) -> float:
        """Density as tipped, before any traffic. Swell reduces density from the in-situ value."""
        return self.insitu_density_t_m3 / (1.0 + self.swell)

    @property
    def compacted_density_t_m3(self) -> float:
        """Density after the layer has been trafficked to refusal."""
        return self.loose_density_t_m3 / (1.0 - self.max_compaction)

    def density_after_passes(self, passes: float) -> float:
        """Density of a layer after ``passes`` equipment passes over it.

        Compaction approaches its limit rather than reaching it linearly: the first passes do most of
        the work and later ones add little, which is why the field guidance is a range of 20 to 30
        passes rather than a single figure. Modelled as an exponential approach with a time constant
        set so that ``PASSES_FOR_FULL_COMPACTION`` reaches about 95 percent of the achievable gain.
        """
        if passes <= 0:
            return self.loose_density_t_m3
        k = 3.0 / PASSES_FOR_FULL_COMPACTION      # exp(-3) is about 5 percent remaining
        frac = 1.0 - math.exp(-k * passes)
        comp = self.max_compaction * frac
        return self.loose_density_t_m3 / (1.0 - comp)

    def repose_deg(self, *, moisture: float | None = None) -> float:
        """The angle this material actually stands at, given its moisture.

        NOT A CONSTANT. Small amounts of water add capillary cohesion between grains and the pile
        stands steeper; past saturation the water separates the grains, cohesion is lost and the angle
        collapses. So the curve rises and then falls, and a model that treats repose as a fixed
        property of the ore cannot represent a wet stockpile at all.

        The shape is a published qualitative relationship rather than a fitted curve, and the product
        must say so. What is defensible is the direction and the existence of a peak, not the exact
        value at any given moisture. UNVERIFIED as a quantitative model.
        """
        w = self.moisture if moisture is None else moisture
        if w <= 0.0:
            return self.repose_dry_deg
        if w >= self.saturation_moisture:
            # Saturated: cohesion is gone and the material spreads. Floors at two thirds of dry, which
            # keeps it a pile rather than a puddle; the true wet limit depends on the fines and is not
            # something this model can claim.
            return self.repose_dry_deg * 0.66
        # Peak at roughly a third of the way to saturation, adding a few degrees at most.
        peak = self.saturation_moisture / 3.0
        gain = 5.0 * math.sin(math.pi * min(w / self.saturation_moisture, 1.0))
        drop = 0.0 if w <= peak else (w - peak) / (self.saturation_moisture - peak) * 8.0
        return max(self.repose_dry_deg + gain - drop, self.repose_dry_deg * 0.66)

    def is_wet(self) -> bool:
        """Whether the dry angle of repose has stopped being valid.

        The ingestion contract flags moisture above 20 percent for exactly this reason: past that
        point the handling behaviour is different and a dry-angle model is being applied outside its
        range.
        """
        return self.moisture >= self.saturation_moisture

    def tonnes_from_loose_m3(self, volume_m3: float) -> float:
        return volume_m3 * self.loose_density_t_m3

    def loose_m3_from_tonnes(self, tonnes: float) -> float:
        return tonnes / self.loose_density_t_m3

    def insitu_m3_from_tonnes(self, tonnes: float) -> float:
        """Volume this tonnage occupied IN THE GROUND, which is what reconciles against the pit."""
        return tonnes / self.insitu_density_t_m3


# The default the rest of the engine uses when a caller does not supply one.
DEFAULT_MATERIAL = Material()


@dataclass(frozen=True)
class SizeSplit:
    """A two-species size split of one parcel of material.

    Two species rather than a full distribution because that is what the segregation solver in this
    package integrates, and because the measured statements are all binary: coarse runs to the toe,
    fines stay central. A full particle-size distribution would be a different model and a much larger
    claim.
    """

    coarse: float
    fine: float

    def __post_init__(self) -> None:
        total = self.coarse + self.fine
        if total <= 0 or abs(total - 1.0) > 1e-9:
            raise ValueError(f"a size split must sum to one, got coarse+fine = {total}")

    @classmethod
    def of(cls, coarse_fraction: float) -> SizeSplit:
        c = min(max(coarse_fraction, 0.0), 1.0)
        return cls(coarse=c, fine=1.0 - c)

    def blended_repose_deg(self, mat: Material) -> float:
        """Repose angle of a mixture, interpolated between the two species.

        A segregated pile "often has a slightly larger angle of repose at the top compared to the base
        of the pile", and this is the mechanism: the top is finer where the coarse has run off, and the
        two species do not stand at the same angle.
        """
        return self.coarse * mat.repose_coarse_deg + self.fine * mat.repose_fine_deg
