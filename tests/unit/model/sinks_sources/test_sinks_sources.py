from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.forcing.validation import (
    ensure_finite_numeric_payload,
    ensure_non_negative_numeric_payload,
    has_temporal_index,
    numeric_payload_array,
)
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig as FlowEtpConfig_2
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.modflow6.builders._lake_outlets import _emit_forcing_rows

# MODFLOW 6 LAK reads every lake forcing as zero or more and stops on a negative one.
#
# The lake guide wrote withdrawals as negative values, and nothing flipped the
# sign, so MODFLOW 6 aborted with 'Withdrawal must be positive'.


SEASONS = {"DJF": 0.01, "MAM": 0.03, "JJA": 0.05, "SON": 0.02}


def _lake(**forcings: object) -> FlowLakeConfig:
    return FlowLakeConfig.model_validate({"initial_stage": 100.0, "bedleak": 1e-6, **forcings})


@pytest.mark.parametrize("keyword", ["rainfall", "evaporation", "runoff", "inflow", "withdrawal"])
def test_a_negative_constant_forcing_is_refused_with_the_convention(keyword: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _lake(**{keyword: {"kind": "constant", "value": -0.01}})
    message = str(excinfo.value)
    assert f"Lake {keyword} = -0.01" in message
    assert f"MODFLOW 6 LAK reads {keyword.upper()}" in message
    assert "zero or more" in message


def test_a_negative_season_of_a_withdrawal_is_refused() -> None:
    with pytest.raises(ValidationError, match="Write withdrawal as a positive rate"):
        _lake(withdrawal={"kind": "seasonal", "by_season": {**SEASONS, "JJA": -0.05}})


def test_a_negative_segment_of_a_piecewise_inflow_is_refused() -> None:
    with pytest.raises(ValidationError, match="Lake inflow = -2"):
        _lake(
            inflow={
                "kind": "piecewise",
                "segments": [
                    {"start": "2020-01-01", "forcing": {"kind": "constant", "value": 1.0}},
                    {"start": "2021-01-01", "forcing": {"kind": "constant", "value": -2.0}},
                ],
            }
        )


def test_a_positive_seasonal_withdrawal_is_accepted() -> None:
    lake = _lake(withdrawal={"kind": "seasonal", "units": "m3/s", "by_season": SEASONS})
    assert lake.withdrawal.by_season == SEASONS


def test_a_negative_value_read_from_a_file_stops_the_build() -> None:
    forcing = {"kind": "values", "values": [0.01, -0.02]}
    with pytest.raises(SolverInputError, match="period 2"):
        _emit_forcing_rows(
            SimpleNamespace(nper=2, time_grid=None),
            lake_index=0,
            lake_id="lac0",
            keyword="withdrawal",
            forcing=forcing,
            volumetric=True,
            mode="inline",
            min_periods=120,
            nper=2,
            period_rows={},
            ts_series=[],
        )


# The soil marker on the ETP payload is a private attribute, never a TOML key.
#
# A field would be a second mechanism beside ``"etp"`` in
# ``flow.active_sinks_sources``; a private attribute enters no TOML, no persisted
# config and no doc, and only ``apply_etp_load_result_to_flow`` may set it.


def test_the_default_etp_is_not_marked() -> None:
    assert FlowEtpConfig().from_soil_reservoir is False


def test_the_marker_survives_a_model_copy() -> None:
    etp = FlowEtpConfig()
    etp._from_soil_reservoir = True

    copied = etp.model_copy(update={"values": 1.0})

    assert copied.from_soil_reservoir is True


def test_the_marker_survives_a_deepcopy() -> None:
    etp = FlowEtpConfig()
    etp._from_soil_reservoir = True

    assert copy.deepcopy(etp).from_soil_reservoir is True


def test_a_toml_key_cannot_set_the_marker() -> None:
    with pytest.raises(ValidationError):
        FlowEtpConfig(from_soil_reservoir=True)


# The spatial source of a recharge or ETP forcing: its mode, its interpolation and its record.
#
# ``spatial_mode`` and ``interpolation_method`` are read by the forcing path on
# cells (``hydromodpy.model.forcing``), ``heterogeneous_source`` holds the
# records it reads.


CONFIGS = pytest.mark.parametrize("config", [FlowRechargeConfig, FlowEtpConfig_2])


def _one_pixel_source() -> LoadResult:
    grid = xr.Dataset(
        {"recharge": (("y", "x"), np.full((1, 1), 5.0))}, coords={"x": [0.5], "y": [0.5]}
    )
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=grid,
        bbox=(0, 0, 1, 1),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


@pytest.mark.fast
def test_the_recharge_keeps_its_heterogeneous_source_as_given():
    source = _one_pixel_source()

    config = FlowRechargeConfig(
        values=0.0, heterogeneous_source=source, first_clim="mean", units="m/s"
    )

    assert config.heterogeneous_source is source


@pytest.mark.fast
def test_the_recharge_has_no_heterogeneous_source_by_default():
    assert FlowRechargeConfig(values=1.0e-8).heterogeneous_source is None


@pytest.mark.fast
@CONFIGS
def test_the_forcing_configs_choose_the_spatial_mode_from_the_source_by_default(config):
    assert config().spatial_mode == "auto"


@pytest.mark.fast
@CONFIGS
def test_the_forcing_configs_keep_nearest_as_default(config):
    assert config().interpolation_method == "nearest"


@CONFIGS
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spatial_mode", "homogeneous"),
        ("interpolation_method", "idw"),
        ("interpolation_method", "area"),
    ],
)
def test_the_forcing_configs_accept_a_known_spatial_choice(config, field, value):
    assert getattr(config(**{field: value}), field) == value


@CONFIGS
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spatial_mode", "invalid"),
        ("interpolation_method", "cubic"),
        ("interpolation_method", "bilinear"),
    ],
)
def test_the_forcing_configs_refuse_an_unknown_spatial_choice(config, field, value):
    with pytest.raises(ValidationError, match=field):
        config(**{field: value})


# Unit tests for numeric forcing validators.


def test_numeric_payload_validators_preserve_nested_labels() -> None:
    ensure_finite_numeric_payload({"rch": [1.0, 0.0]}, label="forcing")
    ensure_non_negative_numeric_payload({"rch": [1.0, 0.0]}, label="forcing")

    with pytest.raises(ValueError, match=r"forcing\['bad'\] must be non-negative"):
        ensure_non_negative_numeric_payload({"bad": [2.0, -0.1]}, label="forcing")
    with pytest.raises(ValueError, match=r"forcing\['well'\] must contain only finite"):
        ensure_finite_numeric_payload({"well": [1.0, np.nan]}, label="forcing")


def test_numeric_payload_array_rejects_empty_bool_and_non_numeric_values() -> None:
    assert numeric_payload_array(2.5, label="forcing").tolist() == [2.5]

    with pytest.raises(TypeError, match="must be numeric"):
        numeric_payload_array(True, label="forcing")
    with pytest.raises(ValueError, match="cannot be empty"):
        numeric_payload_array([], label="forcing")
    with pytest.raises(TypeError, match="numeric sequence"):
        numeric_payload_array(["bad"], label="forcing")


def test_has_temporal_index_detects_datetime_like_labels() -> None:
    import pandas as pd

    assert has_temporal_index(pd.Series([1.0], index=pd.to_datetime(["2020-01-01"])))
    assert has_temporal_index(pd.Series([1.0], index=["2020-01-01"]))
    assert not has_temporal_index(pd.Series([1.0], index=[0]))
    assert not has_temporal_index(object())
