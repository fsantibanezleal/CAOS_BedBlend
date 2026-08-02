"""Methods 9, 10 and 11: the variance reduction ratio, the variogram and the ideal bound.

The first test in this file is the most important one in the repository. The variance reduction ratio
has two reciprocal conventions in circulation, the plan's seed used the wrong one, and building
against it would have inverted every number in the product and made the recommendation layer advise
the worse stacking method with apparent confidence. So the direction is pinned by a test, not by a
comment.
"""
from __future__ import annotations

import math

from bedblend import blending


def test_vrr_is_out_over_in_so_lower_is_better():
    """Pinned against Loubser and de Korte 2015 Table IV: cone shell 0.232 is WORSE than chevcon 0.121."""
    good = blending.vrr(var_in=1.0, var_out=0.121)
    bad = blending.vrr(var_in=1.0, var_out=0.232)
    assert good < bad
    assert abs(good - 0.121) < 1e-12
    assert "var_out / var_in" in blending.VRR_FORMULA_LABEL


def test_vrr_of_an_unvaried_input_is_infinite_rather_than_a_division_by_zero():
    assert math.isinf(blending.vrr(0.0, 0.3))


def test_variance_is_tonnage_weighted_not_count_weighted():
    """Kumral requires both variances on the same base; cuts and dumps are not the same size."""
    values = [1.0, 3.0]
    equal = blending.tonnage_weighted_variance(values, [1.0, 1.0])
    skewed = blending.tonnage_weighted_variance(values, [9.0, 1.0])
    assert abs(equal - 1.0) < 1e-12
    assert skewed < equal, "a heavily weighted first sample must pull the variance down"


def test_the_ideal_bound_is_one_over_n():
    assert abs(blending.vrr_ideal(25.0) - 0.04) < 1e-12
    assert abs(blending.mixing_effect(1.0, 0.04) - 5.0) < 1e-12


def test_efficiency_is_capped_at_one_and_reports_the_published_shortfall():
    """A real bed at E = 5 to 7.5 over 200 to 600 layers recovers a fraction of the ideal.

    Schramm (AT MINERALS PROCESSING 06/2021) reports those mixing effects; the ideal sqrt(N) for the
    same layer counts is 14.1 to 24.5. This test encodes the resulting efficiency range so that a
    future change which quietly starts reporting near-ideal blending for a real bed fails here.
    """
    for n_layers, e in ((200, 5.0), (600, 7.5)):
        achieved = 1.0 / (e * e)
        eff = blending.blending_efficiency(achieved, n_layers)
        assert 0.0 < eff < 0.35, f"N={n_layers}, E={e} gave efficiency {eff:.3f}"
    assert blending.blending_efficiency(0.001, 25.0) == 1.0, "efficiency must be capped at one"


def test_variogram_recovers_the_dig_sequence_structure():
    """A stream built from dig blocks must show a semivariogram that rises with lag and fits a range.

    The range is not an input here. It is a CONSEQUENCE of how long the shovel dwells in one block,
    which is the correction this engine version makes: an operation controls the dig sequence, not the
    covariance of its own ore.
    """
    from bedblend.stream import cumulative_tonnes, dig_sequence, payloads_from

    seq = dig_sequence(n_loads=600, seed=5, loads_per_block=25)
    loads = payloads_from(seq, seed=5)
    centres, gamma, counts = blending.experimental_variogram(
        [p.grade for p in loads], cumulative_tonnes(loads), n_lags=24)
    assert len(centres) == 24 and sum(counts) > 1000
    assert gamma[0] < gamma[-1], "the semivariogram must rise with lag"
    model = blending.fit_spherical(centres, gamma, counts)
    assert model["sill"] > 0
    assert model["range"] > 0


def test_a_shorter_shovel_dwell_decorrelates_the_stream_faster():
    """THE CAUSAL CLAIM, tested rather than asserted in prose.

    Shovel dwell is what sets the correlation length of the material arriving at a stockpile:
    consecutive trucks load from the same block, so a short dwell decorrelates quickly and a long one
    keeps whole layers at one grade. Change only the dwell and the measured range must follow.
    """
    from bedblend.stream import dig_sequence, measured_range_t, payloads_from

    def measured(dwell: int) -> float:
        seq = dig_sequence(n_loads=800, seed=9, loads_per_block=dwell)
        return measured_range_t(payloads_from(seq, seed=9), n_lags=60)

    short, long = measured(5), measured(60)
    assert short < long, f"dwell 5 gave range {short:.0f} t, dwell 60 gave {long:.0f} t"
