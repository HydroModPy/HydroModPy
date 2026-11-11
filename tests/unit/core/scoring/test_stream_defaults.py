"""The defaults of the stream-network criterion and the visible-flow threshold, each with its unit.

Two layers read the same criterion, so one object holds each default. A default
that changes what a calibration scores is written here with its unit, and a
visible flow reads as a discharge in m3/s or as a share of the outlet discharge.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.scoring.stream_defaults import (
    DEFAULT_VISIBLE_FLOW,
    GEOMETRIC,
    STREAM_CRITERION_DEFAULTS,
    VALIDITY_PROVENANCE_BY_CODE,
    VALIDITY_PROVENANCE_CODE,
    StreamCriterionDefaults,
    VisibleFlow,
    parse_visible_flow,
)

# One row per default of the criterion: its name, its value and its unit.
_DEFAULTS = [
    pytest.param("tau_specific_ratio", 1.0e-4, "share of the mean basin recharge", id="tau"),
    pytest.param("diagonal_neighbors", True, "flag", id="d8_descent"),
    pytest.param("observed_rasterization", "heads", "rule", id="rasterization"),
    pytest.param("clip_map_to_catchment", True, "flag", id="clip"),
    pytest.param("max_catchment_mismatch", 0.05, "share of the catchment area", id="mismatch"),
    pytest.param("heads_snap_radius_m", 100.0, "m", id="snap_radius"),
    pytest.param("heads_min_drained_area_km2", 0.02, "km2", id="drained_area"),
    pytest.param("alpha_warning_threshold", 0.90, "agreement share", id="alpha_warning"),
    pytest.param("clipping_warning_share", 0.10, "share of the mapped cells", id="clip_share"),
    pytest.param("clipping_warning_gap", 0.05, "agreement gap", id="clip_gap"),
]


@pytest.mark.parametrize(("name", "value", "unit"), _DEFAULTS)
def test_each_default_has_its_value(name, value, unit) -> None:
    assert getattr(STREAM_CRITERION_DEFAULTS, name) == value
    assert unit


def test_the_table_names_every_field_of_the_model() -> None:
    named = {param.values[0] for param in _DEFAULTS}
    assert named == set(StreamCriterionDefaults.model_fields)


def test_a_share_default_stays_between_zero_and_one() -> None:
    shares = ("max_catchment_mismatch", "alpha_warning_threshold", "clipping_warning_share")
    for name in shares:
        assert 0.0 <= getattr(STREAM_CRITERION_DEFAULTS, name) <= 1.0


# One row per text: the visible flow it reads as, as (discharge in m3/s, share of the outlet).
_VISIBLE_FLOW = [
    pytest.param("1 L/s", (1.0e-3, 0.0), id="liters_per_second"),
    pytest.param("0.002 m3/s", (2.0e-3, 0.0), id="cubic_meters_per_second"),
    pytest.param("3600 m3/h", (1.0, 0.0), id="cubic_meters_per_hour"),
    pytest.param("1%", (0.0, 0.01), id="share_of_the_outlet"),
    pytest.param(" 100 % ", (0.0, 1.0), id="the_whole_outlet"),
    pytest.param("0 L/s", (0.0, 0.0), id="geometric"),
]


@pytest.mark.parametrize(("text", "expected"), _VISIBLE_FLOW)
def test_a_visible_flow_reads_in_m3_per_second_or_as_a_share(text, expected) -> None:
    flow = parse_visible_flow(text)
    assert (flow.discharge_m3_s, flow.outlet_share) == pytest.approx(expected)
    assert flow.geometric is (expected == (0.0, 0.0))


# One row per refusal: the value and a phrase the message holds.
_VISIBLE_FLOW_REFUSED = [
    pytest.param("3", "carries no unit", id="bare_number"),
    pytest.param("150%", "at most 100%", id="share_above_the_outlet"),
]


@pytest.mark.parametrize(("text", "phrase"), _VISIBLE_FLOW_REFUSED)
def test_a_visible_flow_without_a_unit_or_above_the_outlet_is_refused(text, phrase) -> None:
    with pytest.raises(ValueError, match=phrase):
        parse_visible_flow(text)


def test_a_visible_flow_is_a_discharge_or_a_share_never_both() -> None:
    with pytest.raises(ValueError, match="not both"):
        VisibleFlow(discharge_m3_s=1.0e-3, outlet_share=0.1)
    with pytest.raises(ValueError, match="finite and positive"):
        VisibleFlow(discharge_m3_s=-1.0)


def test_a_label_reads_back_to_the_same_threshold() -> None:
    for text in ("1 L/s", "5%", "0 L/s"):
        flow = parse_visible_flow(text)
        assert parse_visible_flow(flow.label()) == flow


def test_the_default_visible_flow_is_one_liter_per_second() -> None:
    assert parse_visible_flow(DEFAULT_VISIBLE_FLOW).discharge_m3_s == pytest.approx(1.0e-3)
    assert parse_visible_flow(VisibleFlow()) == GEOMETRIC


def test_a_provenance_code_reads_back_to_its_name() -> None:
    assert VALIDITY_PROVENANCE_BY_CODE == {c: n for n, c in VALIDITY_PROVENANCE_CODE.items()}
