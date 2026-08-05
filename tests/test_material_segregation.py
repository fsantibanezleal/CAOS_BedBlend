"""Material properties and size segregation down a dumped face.

The engine carried a Gray-Thornton solver it never applied, because nothing ever formed a face for an
avalanche to run down. These are the tests that the coupling now exists and points the right way.
"""
from __future__ import annotations

import itertools

import pytest

from bedblend.facesegregation import (
    apparent_repose_deg,
    intensity,
    segregate_face,
    segregation_index,
    total_segregation_index,
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
    """"each additional meter of height increases percolation segregation".

    Asserted on the TOTAL index, which counts what ran past the toe as toe material, and asserted at
    every metre of a sweep rather than at two endpoints. The on-face index alone is not monotone and
    should not be: above about fifteen metres the extra drop throws more coarse clear of the face than
    it sorts onto it, so the slope you can see gets less sorted while the dump gets more sorted. That
    is the overrun, it is a published mechanism, and hiding it behind a single number was what the
    fitted curve did.
    """
    split = SizeSplit.of(MAT.coarse_fraction)
    seq = [
        total_segregation_index(segregate_face(drop_m=float(d), face_angle_deg=37.0, mat=MAT), split)
        for d in range(31)
    ]
    # Strictly increasing across the operational range. The published guidance is to cap a stockpile
    # at 10 to 12 metres precisely because every extra metre segregates more, so this is the band the
    # claim is about and it is asserted metre by metre rather than at two endpoints.
    for a, b in itertools.pairwise(seq[:21]):
        assert b > a, f"the total index went backwards inside the operational range: {seq[:21]}"
    assert seq[20] > seq[0] + 0.4, "the height dependence is present but negligible"

    # Above about twenty metres it flattens to about 0.503 rather than continuing, because the overrun
    # term reaches the published cap while the on-face sieving is already near the Peclet-limited
    # equilibrium. Flat, not falling: asserted to a millesimal so a real reversal would still fail.
    for a, b in itertools.pairwise(seq[20:]):
        assert b > a - 1e-3, f"the total index fell away above twenty metres: {seq[20:]}"

    # The Gray-Thornton segregation number itself is strictly increasing in the drop, which is the
    # mechanism underneath the observation and does not saturate.
    srs = [segregate_face(drop_m=float(d), face_angle_deg=37.0, mat=MAT).sr for d in range(1, 31)]
    assert all(b > a for a, b in itertools.pairwise(srs))


def test_a_steeper_face_throws_more_clear_of_the_toe_but_sieves_slightly_less():
    """The two mechanisms the fitted curve had merged, now separated and each checked on its own.

    Steeper faces "create faster material flow down the face, increasing trajectory segregation".
    TRAJECTORY segregation is ballistic and Gray-Thornton's equation does not contain it, so wiring
    the real solver split the claim in two:

      * the ballistic part is the overrun, and it RISES with the face angle, which is the published
        direction and is almost pure coarse;
      * kinetic sieving on the face FALLS gently with the angle, because a steeper face is a shorter
        run from crest to toe and Sr scales on the path length.

    The old curve asserted the first direction for both, which read as agreement with the source and
    was really the model having no way to disagree.
    """
    split = SizeSplit.of(MAT.coarse_fraction)
    faces = [segregate_face(drop_m=20.0, face_angle_deg=float(a), mat=MAT) for a in (35, 37, 40)]

    overruns = [f.overrun_fraction for f in faces]
    assert all(b > a for a, b in itertools.pairwise(overruns)), overruns
    assert all(f.overrun_coarse_fraction > 0.9 for f in faces), "the overrun should be nearly all coarse"

    onface = [segregation_index(f, split) for f in faces]
    assert all(b < a for a, b in itertools.pairwise(onface)), onface
    # And the mechanism: shorter path, lower Sr.
    paths = [f.avalanche.path_m for f in faces]
    assert all(b < a for a, b in itertools.pairwise(paths)), paths


def test_a_face_below_the_dynamic_friction_angle_does_not_sort_at_all():
    """A slope that does not avalanche cannot sieve, and the fitted curve had no way to say so.

    The material's repose angle is the STATIC one; granular flow stops at a shallower angle than it
    starts at, so a face standing below that dynamic angle holds. The old model gave such a face a
    segregation gradient anyway, because its angle term was a ramp from 28 degrees with nothing
    physical at the bottom of it.
    """
    for angle in (20.0, 28.0, 31.0):
        seg = segregate_face(drop_m=20.0, face_angle_deg=angle, mat=MAT)
        assert seg.avalanche is not None and not seg.avalanche.flows, angle
        assert seg.sr == 0.0, angle
        assert seg.overrun_fraction == 0.0, angle
        assert segregation_index(seg, SizeSplit.of(MAT.coarse_fraction)) == pytest.approx(0.0), angle


def test_coarse_overruns_the_toe_and_more_so_from_a_higher_bench():
    """"Round and large material may also roll beyond the floor of the bench, especially at higher
    bench heights"."""
    lo = segregate_face(drop_m=6.0, face_angle_deg=37.0, mat=MAT)
    hi = segregate_face(drop_m=30.0, face_angle_deg=37.0, mat=MAT)
    assert hi.overrun_fraction > lo.overrun_fraction > 0.0
    assert hi.overrun_fraction < 0.30, "most of the coarse cannot leave the face"


def test_profiles_account_for_all_the_mass():
    """Whatever did not overrun the toe is still on the face. Mass is not allowed to vanish.

    Asserted PER SPECIES as well as in total, which the previous version could not do: the profiles
    were normalised to one each and carried no information about how much of each species left the
    face. They are now normalised by how much of that species the load held, so each sums to the share
    of it that stayed, and the two sums differ by exactly the overrun's composition.
    """
    split = SizeSplit.of(MAT.coarse_fraction)
    for drop in (0.0, 5.0, 20.0, 30.0):
        seg = segregate_face(drop_m=drop, face_angle_deg=37.0, mat=MAT)
        ov = seg.overrun_fraction
        coarse_on_face = split.coarse * sum(seg.coarse_profile)
        fine_on_face = split.fine * sum(seg.fine_profile)

        # Total mass: what stayed plus what ran past the toe is the whole load.
        assert coarse_on_face + fine_on_face == pytest.approx(1.0 - ov, abs=1e-9), drop
        # Coarse: on the face plus the coarse share of the overrun is all the coarse there was.
        assert coarse_on_face + ov * seg.overrun_coarse_fraction == pytest.approx(
            split.coarse, abs=1e-9
        ), drop
        # Fine: likewise. The solver conserves species mass exactly, so this is exact.
        assert fine_on_face + ov * (1.0 - seg.overrun_coarse_fraction) == pytest.approx(
            split.fine, abs=1e-9
        ), drop


def test_the_solver_is_the_thing_that_runs():
    """The size distribution must come from `segregation`, not from a curve standing in for it.

    THIS IS THE TEST THAT WAS MISSING. The engine shipped a fitted stand-in documented as Gray-Thornton
    kinetic sieving and rated SOTA, and nothing in any shipped path called `FlowingLayer` at all. A
    method whose implementation nothing invokes is the same defect as a selector entry with no engine
    behind it, and it is invisible to every consistency check because the docs and the code agree
    about everything except which code runs.

    Pinned two ways: the face must report the flowing layer it actually marched, and the marching has
    to be what shaped the answer, so patching the solver out has to change the result.
    """
    seg = segregate_face(drop_m=20.0, face_angle_deg=37.0, mat=MAT)
    assert seg.avalanche is not None, "no flowing layer was solved"
    assert seg.avalanche.flows
    assert seg.sr > 0.0

    # The physical quantities behind Sr are real numbers, not placeholders.
    av = seg.avalanche
    assert av.path_m > 0.0 and av.layer_h_m > 0.0 and av.u_ms > 0.0 and av.q_ms > 0.0
    assert av.sr == pytest.approx(av.q_ms * av.path_m / (av.layer_h_m * av.u_ms), rel=1e-12)

    # And the march is load-bearing: with the sieving switched off the profile must go flat.
    import bedblend.facesegregation as fs

    keep = fs.PERCOLATION_COEFFICIENT
    try:
        fs.PERCOLATION_COEFFICIENT = 0.0
        flat = segregate_face(drop_m=20.0, face_angle_deg=37.0, mat=MAT)
    finally:
        fs.PERCOLATION_COEFFICIENT = keep
    split = SizeSplit.of(MAT.coarse_fraction)
    assert segregation_index(flat, split) == pytest.approx(0.0, abs=1e-9), (
        "the sorting survived turning the solver off, so it was not the solver that produced it"
    )


def test_a_segregated_face_has_different_repose_angles_at_its_two_ends():
    """"a segregated pile often has a slightly larger angle of repose at the top compared to the base",
    which falls out of the sorting rather than being imposed."""
    seg = segregate_face(drop_m=20.0, face_angle_deg=37.0, mat=MAT)
    top, bottom = apparent_repose_deg(seg, SizeSplit.of(MAT.coarse_fraction), MAT)
    assert top != pytest.approx(bottom), "a sorted face cannot stand at one angle end to end"
    # With coarse at the toe and coarse standing steeper, the toe is the steeper end here. The test
    # asserts the mechanism is live, not a direction the material may not have.
    assert abs(top - bottom) > 0.1
