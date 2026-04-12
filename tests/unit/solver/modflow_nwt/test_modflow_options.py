from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_nwt.modflow import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig


def test_preprocess_options_defaults_are_stable():
    options = ModflowPreprocessOptions()

    assert options.box is True
    assert options.sink_fill is False
    assert options.check_grid is True
    assert options.time_grid is None


def test_preprocess_options_no_recharge_or_first_clim_fields():
    options = ModflowPreprocessOptions()

    assert not hasattr(options, "recharge")
    assert not hasattr(options, "first_clim")
    assert not hasattr(options, "plot_cross")
    assert not hasattr(options, "cross_ylim")


def test_run_options_defaults_match_processing_signature():
    options = ModflowRunOptions()

    assert options.write_model is True
    assert options.run_model is False
    assert options.link_mt3dms is False
    assert options.verbose is True


def test_postprocess_options_defaults_are_stable():
    options = ModflowPostprocessOptions()

    assert options.watertable_elevation is True
    assert options.watertable_depth is True
    assert options.seepage_areas is True
    assert options.outlet_discharge_east_side_m3_s is False
    assert options.export_all_tif is False


# --- FlowRechargeConfig ---

def test_recharge_config_defaults():
    cfg = FlowRechargeConfig()

    assert cfg.values == 0.0
    assert cfg.first_clim == "mean"
    assert cfg.units == "mm/day"
    assert cfg.negative_to_evt is True


def test_recharge_config_first_clim_normalized_to_lowercase():
    cfg = FlowRechargeConfig(values=0.001, first_clim="MEAN")

    assert cfg.first_clim == "mean"


def test_recharge_config_first_clim_accepts_first():
    cfg = FlowRechargeConfig(values=0.001, first_clim="first")

    assert cfg.first_clim == "first"


def test_recharge_config_first_clim_accepts_numeric():
    cfg = FlowRechargeConfig(values=0.001, first_clim=0.0005)

    assert cfg.first_clim == pytest.approx(0.0005)


def test_recharge_config_first_clim_rejects_unknown_keyword():
    with pytest.raises(ValueError, match="first_clim must be"):
        FlowRechargeConfig(values=0.001, first_clim="median")


def test_recharge_config_accepts_list_values():
    cfg = FlowRechargeConfig(values=[0.001, 0.0008, -0.0002], negative_to_evt=True)

    assert cfg.values == [0.001, 0.0008, -0.0002]
    assert cfg.negative_to_evt is True


def test_recharge_config_negative_to_evt_default_true():
    cfg = FlowRechargeConfig(values=0.001)

    assert cfg.negative_to_evt is True
