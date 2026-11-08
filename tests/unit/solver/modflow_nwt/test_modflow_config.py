from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.catchment.algorithms.flow_products import FlowProducts
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError, ExtractError, SolverInputError
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.model import ModelTime
from hydromodpy.model.properties.property_table import resolve_required_flow_properties
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.modflow6 import Modflow6Config
from hydromodpy.solver.modflow_common.options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow_common.routing_context import (
    SolverRoutingContext,
    build_solver_routing_context,
)
from hydromodpy.solver.modflow_grid import (
    build_temporal_discretization_from_time_grid,
    resolve_first_period_steady,
)
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.extractors.flow import (
    ModflowNwtOutputAdapter,
    _listing_path,
)
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig, ModflowSpecifParams
from hydromodpy.solver.modflow_nwt.nwt.payloads.chd import refuse_constant_heads_below_bottom
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests._helpers.terrain_doubles import fake_flow_products

from ._test_forcing_adapter_builders import _build_solver_mesh


def test_modflow_config_defaults_match_runtime_defaults():
    cfg = ModflowConfig()
    params = ModflowSpecifParams.from_config(cfg)

    assert params.runtime.nwt.version == "mfnwt"
    assert params.runtime.nwt.headtol == 1e-4
    assert params.runtime.nwt.fluxtol == 500.0 / 86400.0
    assert params.runtime.nwt.linmeth == 2
    assert params.process_specific.vka == 1.0
    assert params.process_specific.exdp == 1.0
    assert isinstance(params.sgrid, SolverSGridConfig)
    assert params.sgrid.top_sampling.mode == "centroid"


def test_modflow6_runtime_defaults_keep_xt3d_in_auto_mode():
    cfg = Modflow6Config()

    assert cfg.runtime.mf6_enable_xt3d is None


def test_modflow_config_accepts_exdp_with_unit_string():
    cfg = ModflowConfig.model_validate(
        {
            "process_specific": {
                "vka": 1.0,
                "exdp": "1.5 m",
            }
        }
    )
    assert cfg.process_specific.exdp == pytest.approx(1.5)


def test_hydromodpy_config_loads_modflow_nested_sections(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

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
                'dem_init_path = "dem.tif"',
                "[solver]",
                'backend = "modflow_nwt"',
                "",
                "[solver.modflow_nwt.runtime.nwt]",
                'options = "SIMPLE"',
                "",
                "[solver.modflow_nwt.process_specific]",
                "vka = 2.5",
                "exdp = 3.0",
                "",
                "[mesh.regular]",
                "shape = [5, 6]",
                "",
                "[domain.layers]",
                'genmtd_lay = "decay"',
                "nlay = 3",
                "lay_decay = 1.8",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.solver.backend_name == "modflow_nwt"
    assert cfg.solver.options_of("modflow_nwt").process_specific.vka == 2.5
    assert cfg.solver.options_of("modflow_nwt").process_specific.exdp == 3.0
    assert cfg.solver.options_of("modflow_nwt").runtime.nwt.options == "SIMPLE"
    assert isinstance(cfg.solver.options_of("modflow_nwt").sgrid, SolverSGridConfig)
    assert cfg.mesh.regular.shape == (5, 6)
    assert cfg.domain.layers.genmtd_lay == "decay"
    assert cfg.domain.layers.nlay == 3
    assert cfg.domain.layers.lay_decay == 1.8


def test_hydromodpy_config_rejects_legacy_flat_sgrid_payload(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

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
                'dem_init_path = "dem.tif"',
                "[solver]",
                'backend = "modflow_nwt"',
                "",
                "[solver.modflow_nwt.sgrid]",
                'genmtd_lay = "decay"',
                "nlay = 4",
                "lay_decay = 1.5",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError):
        HydroModPyConfig.from_toml(toml_path)


def test_hydromodpy_config_loads_modflow_exdp_with_unit_string(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

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
                'dem_init_path = "dem.tif"',
                "[solver]",
                'backend = "modflow_nwt"',
                "",
                "[solver.modflow_nwt.process_specific]",
                "vka = 2.5",
                'exdp = "3.0 m"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)
    assert cfg.solver.options_of("modflow_nwt").process_specific.exdp == pytest.approx(3.0)


def test_hydromodpy_config_rejects_legacy_flat_modflow_schema(tmp_path: Path):
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
                'dem_init_path = "dem.tif"',
                "[modflow]",
                "vka = 2.5",
                "exdp = 3.0",
                'nwt_options = "SIMPLE"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError):
        HydroModPyConfig.from_toml(toml_path)


def test_hydromodpy_config_rejects_unknown_top_level_sections(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

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
                'dem_init_path = "dem.tif"',
                "[unexpected]",
                "enabled = true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="Unknown top-level TOML section"):
        HydroModPyConfig.from_toml(toml_path)


def test_hydromodpy_config_loads_independent_modflow6_runtime(tmp_path: Path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

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
                'dem_init_path = "dem.tif"',
                "[solver]",
                'backend = "modflow6"',
                "",
                "[solver.modflow6.runtime]",
                'mf6_executable_name = "mf6_custom"',
                'mf6_ims_complexity = "SIMPLE"',
                "mf6_enable_rewet = true",
                "mf6_enable_xt3d = true",
                "mf6_rewet_wetdry = 0.05",
                "",
                "[solver.modflow6.process_specific]",
                "evt_extinction_depth = 2.5",
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)
    assert cfg.solver.backend_name == "modflow6"
    assert cfg.solver.options_of("modflow6").runtime.mf6_executable_name == "mf6_custom"
    assert cfg.solver.options_of("modflow6").runtime.mf6_ims_complexity == "SIMPLE"
    assert cfg.solver.options_of("modflow6").runtime.mf6_enable_rewet is True
    assert cfg.solver.options_of("modflow6").runtime.mf6_enable_xt3d is True
    assert cfg.solver.options_of("modflow6").runtime.mf6_rewet_wetdry == pytest.approx(0.05)
    assert cfg.solver.options_of("modflow6").process_specific.evt_extinction_depth == pytest.approx(
        2.5
    )


def test_modflownwt_rejects_the_removed_tgrid_section():
    """[solver.modflow_nwt.tgrid] was a mirror nothing read back; the schema refuses it."""
    with pytest.raises(ValueError, match="tgrid"):
        ModflowConfig.model_validate({"tgrid": {"nper": 1}})


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


def test_recharge_config_accepts_non_negative_list_values():
    cfg = FlowRechargeConfig(values=[0.001, 0.0008, 0.0002])

    assert cfg.values == [0.001, 0.0008, 0.0002]


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_recharge_config_rejects_invalid_numeric_values(value):
    with pytest.raises(ValueError):
        FlowRechargeConfig(values=value)


def test_recharge_config_accepts_negative_values_when_routed_to_evt():
    cfg = FlowRechargeConfig(values=[0.001, -0.0002])

    assert cfg.negative_to_evt is True
    assert cfg.values == [0.001, -0.0002]


def test_recharge_config_rejects_negative_values_when_evt_routing_disabled():
    with pytest.raises(ValueError, match="non-negative"):
        FlowRechargeConfig(values=[0.001, -0.0002], negative_to_evt=False)


def test_build_temporal_discretization_from_time_grid_treats_steady_as_all_steady() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0),
        nstp_per_period=4,
        window=None,
    )

    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid,
        flow_regime="steady",
        first_period_steady=False,
    )

    assert result.nper == 3
    assert np.allclose(result.perlen, np.array([1.0, 2.0, 3.0]))
    assert np.array_equal(result.nstp, np.array([4, 4, 4]))
    assert np.array_equal(result.steady, np.array([True, True, True]))


def test_build_temporal_discretization_from_time_grid_uses_first_period_steady() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0),
        nstp_per_period=1,
        window=None,
    )

    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid,
        flow_regime="transient",
        first_period_steady=False,
    )

    assert np.array_equal(result.steady, np.array([False, False, False]))


def test_build_temporal_discretization_from_time_grid_defaults_first_period_steady() -> None:
    time_grid = SimpleNamespace(
        period_lengths_seconds=(1.0, 2.0, 3.0),
        nstp_per_period=1,
        window=None,
    )

    result = build_temporal_discretization_from_time_grid(
        time_grid=time_grid,
        flow_regime="transient",
    )

    assert np.array_equal(result.steady, np.array([True, False, False]))


def _transient_model(*, first_period_steady: bool):
    return make_model(
        time=ModelTime(grid=None, regime="transient", first_period_steady=first_period_steady)
    )


def test_resolve_first_period_steady_uses_explicit_flow_config() -> None:
    model = _transient_model(first_period_steady=False)

    assert resolve_first_period_steady(model=model) is False


def test_resolve_first_period_steady_uses_flow_config_default() -> None:
    model = _transient_model(first_period_steady=True)

    assert resolve_first_period_steady(model=model) is True
    assert resolve_first_period_steady() is True
    assert resolve_first_period_steady(default=False) is False


def test_resolve_required_flow_properties_steady_requires_only_k() -> None:
    assert resolve_required_flow_properties(flow_regime="steady") == frozenset({"K"})


def test_resolve_required_flow_properties_transient_requires_k_sy_ss() -> None:
    assert resolve_required_flow_properties(flow_regime="transient") == frozenset({"K", "Sy", "Ss"})


def test_resolve_required_flow_properties_unknown_regime_defaults_to_full_set() -> None:
    assert resolve_required_flow_properties(flow_regime="unknown") == frozenset({"K", "Sy", "Ss"})


def test_build_solver_routing_context_wraps_flow_products(monkeypatch, tmp_path: Path):
    dem_path = tmp_path / "solver_dem.tif"
    dem_path.write_text("stub", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_build_regional_flow_products(
        *,
        dem_init_path,
        dem_out_dir_path,
        dem_correc_type,
        crs_project,
        backend,
        engine_id,
        capped_breach,
    ):
        captured.update(
            {
                "dem_init_path": str(dem_init_path),
                "dem_out_dir_path": str(dem_out_dir_path),
                "dem_correc_type": dem_correc_type,
                "crs_project": crs_project,
                "backend": backend,
                "engine_id": engine_id,
                "capped_breach": capped_breach,
            }
        )
        return fake_flow_products(
            correc=str(Path(dem_out_dir_path) / "dem_breach.tif"),
            direc=str(Path(dem_out_dir_path) / "dem_direc.tif"),
            acc=str(Path(dem_out_dir_path) / "dem_acc.tif"),
        )

    monkeypatch.setattr(
        "hydromodpy.solver.modflow_common.routing_context.build_regional_flow_products",
        _fake_build_regional_flow_products,
    )

    ctx = build_solver_routing_context(
        dem_path=dem_path,
        output_dir=tmp_path / "routing",
        dem_correc_type="breach",
        crs_project="EPSG:2154",
        backend="fake-wbt",
        engine_id="test-engine",
    )

    assert isinstance(ctx, SolverRoutingContext)
    assert ctx.dem_path == str(dem_path)
    assert ctx.correc_path.endswith("dem_breach.tif")
    assert ctx.direc_path.endswith("dem_direc.tif")
    assert ctx.acc_path.endswith("dem_acc.tif")
    assert captured["dem_init_path"] == str(dem_path)
    assert captured["dem_correc_type"] == "breach"
    assert captured["crs_project"] == "EPSG:2154"
    assert captured["backend"] == "fake-wbt"
    # The solver routes over its own DEM and has to do it with the engine the
    # geographic configuration named, or the reaches of a stream package follow
    # a different talweg from the one the catchment was delineated with.
    assert captured["engine_id"] == "test-engine"


def test_build_solver_routing_context_requires_existing_dem(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Solver DEM raster not found"):
        build_solver_routing_context(
            dem_path=tmp_path / "missing_solver_dem.tif",
            output_dir=tmp_path / "routing",
            dem_correc_type="breach",
        )


# MODFLOW-NWT listing resolution and mass-balance parsing.

_LISTING = """MODFLOW-NWT-SWR1
                     VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1 IN STRESS PERIOD    1
  ---------------------------------------------------------------------------

     CUMULATIVE VOLUMES      L**3       RATES FOR THIS TIME STEP      L**3/T
     ------------------                 ------------------------

           IN:                                      IN:
           ---                                      ---
             STORAGE =           0.0000               STORAGE =           0.0000
       CONSTANT HEAD =           0.0000         CONSTANT HEAD =           0.0000
            RECHARGE =           1.0000              RECHARGE =           2.0000

            TOTAL IN =           1.0000              TOTAL IN =           2.0000

          OUT:                                     OUT:
          ----                                     ----
             STORAGE =           0.0000               STORAGE =           0.5000
       CONSTANT HEAD =           0.0000         CONSTANT HEAD =           1.5000
            RECHARGE =           0.0000              RECHARGE =           0.0000

           TOTAL OUT =           1.0000             TOTAL OUT =           2.0000

            IN - OUT =           0.0000              IN - OUT =           0.0000

 PERCENT DISCREPANCY =           0.00     PERCENT DISCREPANCY =           0.00

          TIME SUMMARY AT END OF TIME STEP    1 IN STRESS PERIOD    1
                    SECONDS     MINUTES      HOURS       DAYS        YEARS
                    -----------------------------------------------------------
   TIME STEP LENGTH  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
 STRESS PERIOD TIME  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
         TOTAL TIME  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
"""


class _RecordingStore:
    """Minimal store capturing the mass-balance records."""

    def __init__(self) -> None:
        self.mass_balances: list[dict] = []

    def write_mass_balances(self, sim_id: str, records: list[dict]) -> None:
        self.mass_balances = records


def test_listing_uses_the_flopy_list_extension() -> None:
    # FloPy declares the LIST unit as ``.list``; a ``.lst`` lookup never matches
    # and silently empties the mass balance.
    assert _listing_path(Path("/out"), "canut_steady_nwt") == Path("/out/canut_steady_nwt.list")


def test_mass_balance_reads_rates_and_scales_them(tmp_path: Path) -> None:
    listing = tmp_path / "run.list"
    listing.write_text(_LISTING, encoding="utf-8")
    store = _RecordingStore()

    ModflowNwtOutputAdapter()._extract_mass_balance(
        "sim", store, listing, 1.0 / 86400.0, stamp_keys=[(0, 0)]
    )

    assert len(store.mass_balances) == 1
    record = store.mass_balances[0]
    assert record["timestep"] == 0
    assert record["total_in"] == pytest.approx(2.0 / 86400.0)
    assert record["total_out"] == pytest.approx(2.0 / 86400.0)
    assert record["storage_out"] == pytest.approx(0.5 / 86400.0)
    # PERCENT_DISCREPANCY is unitless and must not be scaled.
    assert record["percent_error"] == pytest.approx(0.0)
    assert np.isfinite(record["percent_error"])


def test_unreadable_listing_fails_loudly(tmp_path: Path) -> None:
    listing = tmp_path / "run.list"
    listing.write_text("not a MODFLOW listing", encoding="utf-8")

    with pytest.raises(ExtractError, match="mass balance"):
        ModflowNwtOutputAdapter()._extract_mass_balance(
            "sim", _RecordingStore(), listing, 1.0, stamp_keys=[(0, 0)]
        )


# A constant head below the bottom of its cell is refused before MODFLOW-NWT runs.
#
# MODFLOW-NWT does not stop on such a head: the cell holds no saturated
# thickness, the boundary does not act there, and the budget drifts.


def _adapter(boundary_conditions: dict[str, object], *, nper: int = 1) -> FlowToModflowAdapter:
    dem = np.array([[20.0, 20.0, 20.0], [20.0, 20.0, 20.0]])
    model = make_model(
        boundaries=BoundaryConditionBundle(
            conditions=boundary_conditions, active_ids=tuple(boundary_conditions)
        )
    )
    solver_mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=dem,
        botm=np.stack([dem - 10.0, dem - 20.0]),
        dx=5.0,
        dy=5.0,
    )
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=solver_mesh,
        nper=nper,
        sink_fill=False,
    )


def test_a_static_side_head_below_the_top_layer_is_refused() -> None:
    adapter = _adapter({"west_side": SimpleNamespace(value=5.0)})
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    with pytest.raises(SolverInputError) as excinfo:
        refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=None)
    message = str(excinfo.value)
    assert "MODFLOW-NWT" in message
    assert "flow.bc.west_side: 2 cell(s)" in message
    assert "layer 0 row 0 column 0 (head 5.00 m, bottom 10.00 m, period 1)" in message
    assert "domain.depth_model" in message


def test_a_side_head_above_every_bottom_passes() -> None:
    adapter = _adapter({"west_side": SimpleNamespace(value=15.0)})
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=None)


def test_a_chd_row_below_its_bottom_names_the_period() -> None:
    adapter = _adapter({"east_side": SimpleNamespace(value=[15.0, 8.0])}, nper=2)
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()
    with pytest.raises(SolverInputError) as excinfo:
        refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=chd_spd)
    message = str(excinfo.value)
    assert "flow.bc.east_side" in message
    assert "column 2 (head 8.00 m, bottom 10.00 m, period 2)" in message


def test_the_build_refuses_before_any_package_is_assembled() -> None:
    adapter = _adapter({"west_side": SimpleNamespace(value=5.0)})
    with pytest.raises(SolverInputError, match="flow.bc.west_side"):
        adapter.build()


# A calibration trial's extinction_depth reaches the built NWT EVT package.
#
# Mirrors ``test_a_calibration_trial_value_reaches_the_soil_evt_package.py`` for
# MODFLOW-NWT: ``FlowToModflowAdapter._build_etp_payload`` reads
# ``Model.etp.extinction_depth`` straight off the typed config a trial just
# patched with ``set_by_path``, the same path ``TrialContext.fork`` rebuilds the
# runtime ``Flow`` and its ``Model`` from before every trial solve.


def _adapter_for(etp_cfg: FlowEtpConfig) -> FlowToModflowAdapter:
    model = make_model(
        etp=etp_cfg,
        active_sinks_sources=("etp",),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=_build_solver_mesh(),
        nper=1,
        sink_fill=False,
    )


def _trial_etp(base: FlowEtpConfig, trial_value: float) -> FlowEtpConfig:
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "extinction_depth", trial_value)
    return trial_cfg


def test_a_trial_value_rebuilds_the_evt_depth() -> None:
    base = FlowEtpConfig(values=0.0, units="m/s", extinction_depth=1.0)

    trial_cfg = _trial_etp(base, 9.0)
    adapter = _adapter_for(trial_cfg)

    _evt_spd, _surface_offset, extinction_depth = adapter._build_etp_payload()

    assert extinction_depth == pytest.approx(9.0)


def test_two_trials_move_the_depth_each_time() -> None:
    base = FlowEtpConfig(values=0.0, units="m/s", extinction_depth=1.0)

    depths = [
        _adapter_for(_trial_etp(base, trial_value))._build_etp_payload()[2]
        for trial_value in (3.0, 15.0)
    ]

    assert depths == [pytest.approx(3.0), pytest.approx(15.0)]


@pytest.mark.parametrize(
    ("top_sampling", "refused"),
    [
        ({}, True),
        ({"channel_source": "streams_raster"}, True),
        ({"channel_source": "none"}, False),
        ({"mode": "centroid"}, False),
    ],
    ids=["default source", "channel tree", "median only", "centroid"],
)
def test_a_zonal_top_with_a_channel_source_is_refused_by_the_table(top_sampling, refused) -> None:
    """MODFLOW-NWT reads no channel tree, so the table says so as it is read."""
    document = {"sgrid": {"top_sampling": {"mode": "zonal", **top_sampling}}}
    if refused:
        with pytest.raises(
            ValueError, match="MODFLOW-NWT does not read the channel tree"
        ) as caught:
            ModflowConfig.model_validate(document)
        assert "channel_source = 'none'" in str(caught.value)
        assert "MODFLOW 6" in str(caught.value)
    else:
        assert ModflowConfig.model_validate(document).sgrid.top_sampling is not None
