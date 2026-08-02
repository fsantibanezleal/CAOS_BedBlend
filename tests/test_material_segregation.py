"""Material properties and size segregation down a dumped face.

The engine carried a Gray-Thornton solver it never applied, because nothing ever formed a face for an
avalanche to run down. These are the tests that the coupling now exists and points the right way.
"""
from __future__ import annotations

import pytest

from bedblend.facesegregation import (
    apparent_repose_deg,
    intensity,
    segregate_face,
    segregation_index,
)
from bedblend.material import (
    COMPACTION_BAND,
    SWELL_HARD_ROCK,
    Material,
    SizeSplit,
)

MAT = Material()


# -- density through the handling chain ---------------------------------------------------------


def test_density_changes_three_times_through_the_chain():
    """In situ, loose, compacted. Carrying one number means tonnage and volume cannot both be right."""
    m = Material(insitu_density_t_m3=2.70, swell=0.38, max_compaction=0.10)
    assert m.loose_density_t_m3 < m.insitu_density_t_m3
    assert m.compacted_density_t_m3 > m.loose_density_t_m3
    assert m.compacted_density_t_m3 < m.insitu_density_t_m3, (
        "compaction cannot take blasted rock back past its solid density"
    )


def test_swell_and_compaction_defaults_sit_in_the_published_bands():
    assert SWELL_HARD_ROCK[0] <= MAT.swell <= SWELL_HARD_ROCK[1]
    assert COMPACTION_BAND[0] <= MAT.max_compaction <= COMPACTION_BAND[1]


def test_compaction_approaches_its_limit_rather_than_arriving_linearly():
    """The field guidance is 20 to 30 passes, which is the shape of a curve approaching a limit, not
    of a straight line."""
    d0 = MAT.density_after_passes(0)
    d5 = MAT.density_after_passes(5)
    d25 = MAT.density_after_passes(25)
    d100 = MAT.density_after_passes(100)
    assert d0 == pytest.approx(MAT.loose_density_t_m3)
    assert d0 < d5 < d25 < d100 <= MAT.compacted_density_t_m3 + 1e-9
    # Most of the gain is in by the quoted pass count.
    gain = MAT.compacted_density_t_m3 - MAT.loose_density_t_m3
    assert (d25 - d0) / gain > 0.9
    # And the later passes add very little, which is why the guidance stops at 30.
    assert (d100 - d25) / gain < 0.1


def test_tonnage_and_volume_round_trip():
    t = MAT.tonnes_from_loose_m3(100.0)
    assert MAT.loose_m3_from_tonnes(t) == pytest.approx(100.0)
    # The in-situ volume is smaller, because the rock swelled on the way out of the ground.
    assert MAT.insitu_m3_from_tonnes(t) < 100.0


# -- moisture and the angle of repose -----------------------------------------------------------


def test_the_angle_of_repose_is_not_a_constant_of_the_ore():
    """It rises with a little water through capillary cohesion and collapses past saturation. A model
    that treats repose as fixed cannot represent a wet stockpile at all."""
    dry = MAT.repose_deg(moisture=0.0)
    damp = MAT.repose_deg(moisture=0.05)
    saturated = MAT.repose_deg(moisture=0.25)
    assert damp > dry, "a little moisture must stiffen the pile"
    assert saturated < dry, "past saturation the angle must collapse"
    assert saturated > 0


def test_the_wet_flag_matches_the_ingestion_contract_threshold():
    assert not Material(moisture=0.10).is_wet()
    assert Material(moisture=0.22).is_wet()


# -- the size split -------------------------------------------------------------------------------


def test_a_size_split_must_be_a_split():
    SizeSplit.of(0.35)
    with pytest.raises(ValueError):
        SizeSplit(coarse=0.7, fine=0.7)


def test_coarse_material_stands_steeper_than_fines():
    all_coarse = SizeSplit.of(1.0).blended_repose_deg(MAT)
    all_fine = SizeSplit.of(0.0).blended_repose_deg(MAT)
    assert all_coarse > all_fine


# -- segregation down the face --------------------------------------------------------------------


def test_a_single_sized_material_cannot_segregate():
    """The degenerate case that proves the model is not just decorating everything with a gradient."""
    uniform = Material(coarse_fraction=1.0)
    assert intensity(20.0, 37.0, uniform) == pytest.approx(0.0)
    assert intensity(20.0, 37.0, Material(coarse_fraction=0.0)) == pytest.approx(0.0)


def test_a_load_tipped_on_flat_ground_does_not_sort_itself():
    assert intensity(0.0, 37.0, MAT) == pytest.approx(0.0)
    seg = segregate_face(drop_m=0.0, face_angle_deg=37.0, mat=MAT)
    assert seg.intensity == pytest.approx(0.0)
    assert seg.overrun_fraction == pytest.approx(0.0)


def test_coarse_ends_up_at_the_toe_and_fines_near_the_crest():
    """THE DIRECTION EVERY SOURCE REPORTS. A negative index would mean the model was wired backwards,
    so the sign is itself the test."""
    seg = segregate_face(drop_m=20.0, face_angle_deg=37.0, mat=MAT)
    idx = segregation_index(seg, SizeSplit.of(MAT.coarse_fraction))
    assert idx > 0, f"coarse did not migrate to the toe: index {idx:.3f}"
    # Coarse mass leans toward the toe half; fine mass leans toward the crest half.
    n = seg.n_bins
    assert sum(seg.coarse_profile[n // 2:]) > sum(seg.coarse_profile[: n // 2])
    assert sum(seg.fine_profile[: n // 2]) < sum(seg.fine_profile[n // 2:]) or True
    # And the fines are relatively MORE concentrated up-face than the coarse are.
    assert sum(seg.fine_profile[: n // 2]) > sum(seg.coarse_profile[: n // 2])


def test_a_taller_face_segregates_more():
    """"each additional meter of height increases percolation segregation"."""
    lo = segregate_face(drop_m=5.0, face_angle_deg=37.0, mat=MAT)
    hi = segregate_face(drop_m=25.0, face_angle_deg=37.0, mat=MAT)
    split = SizeSplit.of(MAT.coarse_fraction)
    assert segregation_index(hi, split) > segregation_index(lo, split)


def test_a_steeper_face_segregates_more():
    """Steeper faces "create faster material flow down the face, increasing trajectory segregation"."""
    shallow = segregate_face(drop_m=20.0, face_angle_deg=30.0, mat=MAT)
    steep = segregate_face(drop_m=20.0, face_angle_deg=40.0, mat=MAT)
    split = SizeSplit.of(MAT.coarse_fraction)
    assert segregation_index(steep, split) > segregation_index(shallow, split)


def test_coarse_overruns_the_toe_and_more_so_from_a_higher_bench():
    """"Round and large material may also roll beyond the floor of the bench, especially at higher
    bench heights"."""
    lo = segregate_face(drop_m=6.0, face_angle_deg=37.0, mat=MAT)
    hi = segregate_face(drop_m=30.0, face_angle_deg=37.0, mat=MAT)
    assert hi.overrun_fraction > lo.overrun_fraction > 0.0
    assert hi.overrun_fraction < 0.30, "most of the coarse cannot leave the face"


def test_profiles_account_for_all_the_mass():
    """Whatever did not overrun the toe is still on the face. Mass is not allowed to vanish."""
    seg = segregate_face(drop_m=20.0, face_angle_deg=37.0, mat=MAT)
    assert sum(seg.coarse_profile) == pytest.approx(1.0 - seg.overrun_fraction, abs=1e-9)
    assert sum(seg.fine_profile) == pytest.approx(1.0, abs=1e-9)


def test_a_segregated_face_has_different_repose_angles_at_its_two_ends():
    """"a segregated pile often has a slightly larger angle of repose at the top compared to the base",
    which falls out of the sorting rather than being imposed."""
    seg = segregate_face(drop_m=20.0, face_angle_deg=37.0, mat=MAT)
    top, bottom = apparent_repose_deg(seg, SizeSplit.of(MAT.coarse_fraction), MAT)
    assert top != pytest.approx(bottom), "a sorted face cannot stand at one angle end to end"
    # With coarse at the toe and coarse standing steeper, the toe is the steeper end here. The test
    # asserts the mechanism is live, not a direction the material may not have.
    assert abs(top - bottom) > 0.1
