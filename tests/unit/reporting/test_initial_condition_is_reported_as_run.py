"""The report has to say which steady state the run actually started from.

``[flow.ic] type = "steady_state"`` covers two different statements now: an
equilibrium under the mean of the recharge chronicle, and one under a rate the
study states. The report described both as "the mean recharge of the
series", so a run held at 500 mm/yr was written up as a run held at whatever
the record happened to average.
"""

from __future__ import annotations

from hydromodpy.reporting.comparison.sections.io import _initial_condition_text


def _flow(**ic: object) -> dict[str, object]:
    return {"ic": {"type": "steady_state", **ic}}


def test_the_mean_of_the_record_is_named_as_such() -> None:
    text = _initial_condition_text(_flow(source="mean_recharge"))

    assert "mean recharge" in text


def test_a_prescribed_rate_is_reported_with_its_value() -> None:
    text = _initial_condition_text(_flow(source="prescribed", rate=1.5844e-08))

    assert "mean recharge" not in text
    assert "500" in text


def test_a_prescribed_rate_is_written_in_millimetres_per_year() -> None:
    text = _initial_condition_text(_flow(source="prescribed", rate=1.5844e-08))

    assert "mm/yr" in text


def test_an_unstated_source_still_reads_as_the_mean() -> None:
    """The historical default, and what the normalizer fills in."""
    assert "mean recharge" in _initial_condition_text(_flow())


def test_another_initial_condition_is_untouched() -> None:
    text = _initial_condition_text({"ic": {"type": "top_offset", "value": 2.0}})

    assert "the top minus" in text
