"""The settings a MODFLOW run is read with: backend tables, run options and recharge config.

Defaults of the NWT table, units in strings (``"1.5 m"``), the TOML route into
``HydroModPyConfig``, the options of the pre-process, run and post-process steps, and the
refusals of a recharge series or of a zonal top that needs a channel tree NWT does not read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.model.properties.property_table import resolve_required_flow_properties
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.modflow_common.options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow_common.routing_context import build_solver_routing_context
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig, ModflowSpecifParams


def read_config(tmp_path: Path, backend: str, solver_lines: list[str]) -> HydroModPyConfig:
    (tmp_path / "dem.tif").touch()
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                "",
                "[site]",
                'name = "site_a"',
                "",
                "[geographic]",
                "",
                "[geographic.catchment]",
                'kind = "dem"',
                "[[data.dem.sources]]",
                'source = "file"',
                'path = "inputs/dem.tif"',
                "[solver]",
                f'backend = "{backend}"',
                "",
                *solver_lines,
            ]
        ),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(toml_path)


def test_nwt_defaults():
    params = ModflowSpecifParams.from_config(ModflowConfig())

    assert params.runtime.nwt.version == "mfnwt"
    assert params.runtime.nwt.headtol == 1e-4
    assert params.runtime.nwt.fluxtol == 500.0 / 86400.0
    assert params.runtime.nwt.linmeth == 2
    assert params.process_specific.vka == 1.0
    assert params.process_specific.exdp == 1.0
    assert isinstance(params.sgrid, SolverSGridConfig)
    assert params.sgrid.top_sampling.mode == "centroid"


def test_exdp_with_a_unit_string():
    config = ModflowConfig.model_validate({"process_specific": {"vka": 1.0, "exdp": "1.5 m"}})

    assert config.process_specific.exdp == pytest.approx(1.5)


def test_toml_exdp_with_a_unit_string(tmp_path: Path):
    config = read_config(
        tmp_path,
        "modflow_nwt",
        ["[solver.modflow_nwt.process_specific]", "vka = 2.5", 'exdp = "3.0 m"'],
    )

    assert config.solver.options_of("modflow_nwt").process_specific.exdp == pytest.approx(3.0)


def test_toml_modflow6_runtime(tmp_path: Path):
    config = read_config(
        tmp_path,
        "modflow6",
        [
            "[solver.modflow6.runtime]",
            'mf6_executable_name = "mf6_custom"',
            'mf6_ims_complexity = "SIMPLE"',
            "mf6_enable_rewet = true",
            "mf6_enable_xt3d = true",
            "mf6_rewet_wetdry = 0.05",
            "",
            "[solver.modflow6.process_specific]",
            "evt_extinction_depth = 2.5",
        ],
    )

    options = config.solver.options_of("modflow6")
    assert config.solver.backend_name == "modflow6"
    assert options.runtime.mf6_executable_name == "mf6_custom"
    assert options.runtime.mf6_ims_complexity == "SIMPLE"
    assert options.runtime.mf6_enable_rewet is True
    assert options.runtime.mf6_enable_xt3d is True
    assert options.runtime.mf6_rewet_wetdry == pytest.approx(0.05)
    assert options.process_specific.evt_extinction_depth == pytest.approx(2.5)


def test_step_option_defaults():
    pre = ModflowPreprocessOptions()
    run = ModflowRunOptions()
    post = ModflowPostprocessOptions()

    assert (pre.box, pre.sink_fill, pre.check_grid, pre.time_grid) == (True, False, True, None)
    assert (run.write_model, run.run_model, run.link_mt3dms, run.verbose) == (
        True,
        False,
        False,
        True,
    )
    assert post.watertable_elevation is True
    assert post.watertable_depth is True
    assert post.seepage_areas is True
    assert post.outlet_discharge_east_side_m3_s is False
    assert post.export_all_tif is False


def test_preprocess_options_hold_no_recharge_field():
    options = ModflowPreprocessOptions()

    for name in ("recharge", "first_clim", "plot_cross", "cross_ylim"):
        assert not hasattr(options, name)


def test_numeric_first_clim_is_accepted():
    config = FlowRechargeConfig(values=0.001, first_clim=0.0005)

    assert config.first_clim == pytest.approx(0.0005)


def test_unknown_regime_needs_the_full_property_set():
    assert resolve_required_flow_properties(flow_regime="unknown") == frozenset({"K", "Sy", "Ss"})


def test_routing_context_needs_an_existing_dem(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Solver DEM raster not found"):
        build_solver_routing_context(
            dem_path=tmp_path / "missing_solver_dem.tif",
            output_dir=tmp_path / "routing",
            dem_correc_type="breach",
        )


RECHARGE_REFUSALS = [
    pytest.param({"values": None}, None, id="no value"),
    pytest.param({"values": float("nan")}, None, id="nan"),
    pytest.param({"values": float("inf")}, None, id="inf"),
    pytest.param({"values": 0.001, "first_clim": "median"}, "first_clim must be", id="first_clim"),
    pytest.param(
        {"values": [0.001, -0.0002], "negative_to_evt": False},
        "non-negative",
        id="negative without evt routing",
    ),
]


@pytest.mark.parametrize(("kwargs", "match"), RECHARGE_REFUSALS)
def test_recharge_config_refusals(kwargs, match):
    with pytest.raises(ValueError, match=match):
        FlowRechargeConfig(**kwargs)


ZONAL_TOPS_REFUSED = [
    pytest.param({}, id="default source"),
    pytest.param({"channel_source": "streams_raster"}, id="channel tree"),
]
ZONAL_TOPS_ACCEPTED = [
    pytest.param({"mode": "zonal", "channel_source": "none"}, id="median only"),
    pytest.param({"mode": "centroid"}, id="centroid"),
]


@pytest.mark.parametrize("top_sampling", ZONAL_TOPS_REFUSED)
def test_zonal_top_with_a_channel_source_is_refused(top_sampling):
    # NWT reads no channel tree, so the table says so as it is read.
    document = {"sgrid": {"top_sampling": {"mode": "zonal", **top_sampling}}}

    with pytest.raises(ValueError, match="MODFLOW-NWT does not read the channel tree") as caught:
        ModflowConfig.model_validate(document)

    assert "channel_source = 'none'" in str(caught.value)
    assert "MODFLOW 6" in str(caught.value)


@pytest.mark.parametrize("top_sampling", ZONAL_TOPS_ACCEPTED)
def test_top_sampling_without_a_channel_tree_is_accepted(top_sampling):
    config = ModflowConfig.model_validate({"sgrid": {"top_sampling": top_sampling}})

    assert config.sgrid.top_sampling is not None
