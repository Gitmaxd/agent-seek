"""Wilson intervals and exact binomial tests for published preference rates."""

from __future__ import annotations

import pytest

from apps.api.proportion import (
    Z_95,
    exact_binomial_twosided_p,
    format_p_value,
    format_rate_detail,
    format_wilson_ci,
    proportion_stat,
    wilson_interval,
)


def test_z95_is_the_normal_975_quantile():
    assert Z_95 == pytest.approx(1.959963984540054, rel=0, abs=1e-12)


def test_snip_37_of_50_matches_published_sanity_check():
    stat = proportion_stat(37, 50)
    assert stat.estimate == pytest.approx(0.74)
    assert stat.p_value == pytest.approx(0.000936222911, rel=0, abs=1e-12)
    assert format_p_value(stat.p_value) == "0.0009"
    assert format_wilson_ci(stat.ci_low, stat.ci_high) == "60.4\u201384.1%"
    assert format_rate_detail(stat) == "Wilson 60.4\u201384.1%; p=0.0009"
    # Ties are 0, so the decided-pair rate is the same contrast.
    assert proportion_stat(37, 50).p_value == proportion_stat(13, 50).p_value


def test_deep_32_16_2_reports_both_denominators():
    of_n = proportion_stat(32, 50)
    decided = proportion_stat(32, 48)
    base_of_n = proportion_stat(16, 50)
    base_decided = proportion_stat(16, 48)

    assert of_n.estimate == pytest.approx(0.64)
    assert of_n.p_value == pytest.approx(0.064908647072, rel=0, abs=1e-12)
    assert format_p_value(of_n.p_value) == "0.065"
    assert format_wilson_ci(of_n.ci_low, of_n.ci_high) == "50.1\u201375.9%"

    assert decided.estimate == pytest.approx(32 / 48)
    assert decided.p_value == pytest.approx(0.029304946721, rel=0, abs=1e-12)
    assert format_p_value(decided.p_value) == "0.029"
    assert format_wilson_ci(decided.ci_low, decided.ci_high) == "52.5\u201378.3%"

    # Of n, baseline wins are not the complement of agent-seek wins (2 ties).
    assert base_of_n.p_value == pytest.approx(0.015346677833, rel=0, abs=1e-12)
    assert format_wilson_ci(base_of_n.ci_low, base_of_n.ci_high) == "20.8\u201345.8%"
    # Decided pairs are a complement, so the two-sided p-values match.
    assert base_decided.p_value == decided.p_value
    assert format_wilson_ci(base_decided.ci_low, base_decided.ci_high) == "21.7\u201347.5%"


def test_exact_p_is_one_at_the_mode_and_symmetric():
    assert exact_binomial_twosided_p(25, 50) == 1.0
    assert exact_binomial_twosided_p(0, 1) == pytest.approx(1.0)
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert 0.0 < high < 0.5
    full_low, full_high = wilson_interval(10, 10)
    assert full_high == 1.0
    assert 0.5 < full_low < 1.0


def test_undefined_when_no_trials():
    stat = proportion_stat(0, 0)
    assert not stat.defined
    assert format_rate_detail(stat) == "\u2014"


def test_rejects_impossible_counts():
    with pytest.raises(ValueError):
        proportion_stat(3, 2)
    with pytest.raises(ValueError):
        proportion_stat(-1, 5)
