"""What each metric of the registry computes, written once as a formula.

The kernels compute; this module says what they compute, for the reader. The
documentation renders it on the reference of the calibration methods and on the
theory page of the inverse problem, so no page types a formula of its own. A
unit test keeps the keys equal to ``series.METRICS``: a kernel added without its
formula fails there.

Each formula is LaTeX, written for the score the kernel returns, in the
notation of the theory page: ``s_t`` the simulated value, ``o_t`` the observed
one, ``n`` the number of paired samples. Whether the cost is the score or one
minus the score is not repeated here: ``series.HIGHER_IS_BETTER`` says it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricFormula:
    """The formula of one metric and the mismatch it weighs."""

    score: str
    """LaTeX of the value the kernel returns."""

    reads: str
    """One plain sentence: what kind of mismatch the metric weighs most."""

    where: str = ""
    """LaTeX defining the symbols the formula adds, or empty."""

    note: str = ""
    """Plain text: a condition of use the formula does not show, or empty."""


METRIC_FORMULAS: dict[str, MetricFormula] = {
    "rmse": MetricFormula(
        score=r"\sqrt{\tfrac{1}{n}\sum_t (s_t - o_t)^2}",
        reads="Large misses weigh more than many small ones.",
    ),
    "mae": MetricFormula(
        score=r"\tfrac{1}{n}\sum_t \lvert s_t - o_t \rvert",
        reads="The typical miss, less driven by a few large ones.",
    ),
    "nse": MetricFormula(
        score=r"1 - \dfrac{\sum_t (s_t - o_t)^2}{\sum_t (o_t - \bar{o})^2}",
        reads="The fit against a model that always predicts the observed mean.",
    ),
    "nse_log": MetricFormula(
        score=r"\mathrm{NSE}\big(\ln(s + \varepsilon),\ \ln(o + \varepsilon)\big)",
        reads="The NSE of the logarithms: recessions and low flows weigh as much as the peaks.",
        where=r"\varepsilon = \max\big(10^{-9},\ 0.01\,\mathrm{median}\{o_t > 0\}\big)",
        note="Negative values are clipped to zero first, and the trial counts them.",
    ),
    "kge": MetricFormula(
        score=r"1 - \sqrt{(r - 1)^2 + (\alpha - 1)^2 + (\beta - 1)^2}",
        reads="Correlation, variability and bias in one number.",
        where=r"r = \mathrm{corr}(s, o),\quad \alpha = \sigma_s / \sigma_o,\quad "
        r"\beta = \textstyle\sum_t s_t \big/ \sum_t o_t",
    ),
    "nse_delta": MetricFormula(
        score=r"\mathrm{NSE}(\Delta s,\ \Delta o)",
        reads="The fit of the change from one sample to the next, blind to the absolute level.",
        where=r"\Delta x_t = x_{t+1} - x_t",
        note="Pair it with a metric on the level.",
    ),
    "nse_seasonal": MetricFormula(
        score=r"1 - \dfrac{\sum_t (s_t - o_t)^2}{\sum_t (o_t - c_t)^2}",
        reads="The fit beyond the seasonal cycle of the observations. Below zero, "
        "the model does worse than that cycle alone.",
        where=r"c_t = a_0 + \textstyle\sum_{k=1}^{2} \big(a_k \cos\tfrac{2\pi k t}{365}"
        r" + b_k \sin\tfrac{2\pi k t}{365}\big),\ \text{fitted to } o \text{ by least squares}",
        note="The period is 365 samples and two periods are needed, so the series "
        "has to be daily. A shorter series scores NaN.",
    ),
    "reservoir": MetricFormula(
        score=r"\tfrac{1}{2}\,\mathrm{NSE}_{\mathrm{seasonal}}(s, o) + "
        r"\tfrac{1}{2}\,\mathrm{NSE}(\Delta_{10} s,\ \Delta_{10} o)",
        reads="Built for an impounded level: the seasonal half keeps the level "
        "honest, the increment half makes the water balance count.",
        where=r"\Delta_{10} x_t = x_{t+10} - x_t",
        note="Daily series only, as for nse_seasonal.",
    ),
    "distance_gap": MetricFormula(
        score=r"\lvert D_{so} - D_{os} \rvert",
        reads="Eq. 1 of the stream-network method: zero where the simulated network "
        "reaches as far as the mapped one.",
        where=r"J = D_{so} - D_{os}",
        note="D_so is the mean downslope distance from the simulated network to the "
        "mapped one, D_os the reverse. J is the signed residual a root search "
        "brackets. With two bounds, the cost sums the weighted gap of each bound.",
    ),
    "distance_mean": MetricFormula(
        score=r"\tfrac{1}{2}\,(D_{so} + D_{os})",
        reads="Eq. 2 of the stream-network method: the mean mismatch of the two networks.",
        note="A diagnostic, and a cost only to choose between structures already "
        "balanced by distance_gap. With two bounds, the cost sums the weighted mean "
        "of each bound.",
    ),
}
"""The formula of every metric of ``series.METRICS``, by the name a TOML writes."""


__all__ = ["METRIC_FORMULAS", "MetricFormula"]
