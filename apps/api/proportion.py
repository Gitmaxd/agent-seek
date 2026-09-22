"""Wilson intervals and exact binomial tests for published preference rates.

No SciPy. Trials are small (the public suite is n=50), so the exact test
uses integer binomial coefficients.

Definitions, both at H0: p = 0.5:

* Wilson 95% score interval. The critical value is the standard-normal
  0.975 quantile (``statistics.NormalDist``).
* Two-sided exact binomial p-value by the probability method: the sum of
  H0 point masses no larger than the observed outcome's mass. At p = 0.5
  that mass is proportional to the binomial coefficient. This is the same
  rule as ``scipy.stats.binomtest(..., alternative="two-sided")``. Far
  from the center it equals twice the one-sided tail; at the mode it is 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from math import comb
from statistics import NormalDist

# 95% two-sided normal quantile. Locked so the interval does not depend on
# a hand-copied constant drifting from the stdlib inverse CDF.
Z_95 = NormalDist().inv_cdf(0.975)

_EN_DASH = "\u2013"


@dataclass(frozen=True)
class ProportionStat:
    """One binomial rate with its Wilson interval and exact two-sided p."""

    successes: int
    trials: int
    estimate: float
    ci_low: float | None
    ci_high: float | None
    p_value: float | None

    @property
    def defined(self) -> bool:
        return self.trials > 0 and self.ci_low is not None and self.p_value is not None


def exact_binomial_twosided_p(successes: int, trials: int) -> float:
    """Two-sided exact binomial p-value for H0: p = 0.5."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError(f"invalid binomial count {successes}/{trials}")
    if trials == 0:
        return 1.0
    observed = comb(trials, successes)
    total = 0
    for i in range(trials + 1):
        coefficient = comb(trials, i)
        if coefficient <= observed:
            total += coefficient
    return float(Fraction(total, 1 << trials))


def wilson_interval(
    successes: int,
    trials: int,
    *,
    z: float = Z_95,
) -> tuple[float, float]:
    """Wilson score interval for ``successes / trials``. Bounds lie in [0, 1]."""
    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError(f"invalid binomial count {successes}/{trials}")
    phat = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (phat + z2 / (2.0 * trials)) / denom
    margin = (z / denom) * math.sqrt(
        phat * (1.0 - phat) / trials + z2 / (4.0 * trials * trials)
    )
    low = center - margin
    high = center + margin
    # 0/n and n/n are exactly 0 and 1 in algebra; float error leaves a 1e-16 stub.
    if successes == 0:
        low = 0.0
    if successes == trials:
        high = 1.0
    return min(1.0, max(0.0, low)), min(1.0, max(0.0, high))


def proportion_stat(successes: int, trials: int) -> ProportionStat:
    """Point estimate, Wilson 95% CI, and two-sided exact p against 0.5.

    ``trials == 0`` is undefined: estimate 0 and null interval / p-value.
    """
    successes = int(successes)
    trials = int(trials)
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError(f"invalid binomial count {successes}/{trials}")
    if trials == 0:
        return ProportionStat(successes, 0, 0.0, None, None, None)
    low, high = wilson_interval(successes, trials)
    return ProportionStat(
        successes,
        trials,
        successes / trials,
        low,
        high,
        exact_binomial_twosided_p(successes, trials),
    )


def format_p_value(p: float) -> str:
    """Short p display. Four decimals below 0.001 so 0.000936 reads 0.0009."""
    if p < 0.0001:
        return "<0.0001"
    if p < 0.001:
        return f"{p:.4f}"
    return f"{p:.3f}"


def format_wilson_ci(low: float, high: float) -> str:
    """Percent interval with an en dash, one decimal (``60.4–84.1%``)."""
    return f"{100.0 * low:.1f}{_EN_DASH}{100.0 * high:.1f}%"


def format_rate_detail(stat: ProportionStat) -> str:
    """``Wilson 60.4–84.1%; p=0.0009``, or an em dash when undefined."""
    if not stat.defined:
        return "\u2014"
    assert stat.ci_low is not None and stat.ci_high is not None and stat.p_value is not None
    return (
        f"Wilson {format_wilson_ci(stat.ci_low, stat.ci_high)}; "
        f"p={format_p_value(stat.p_value)}"
    )
