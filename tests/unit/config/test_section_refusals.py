from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigValidationError,
    IncompatibleCapabilitiesError,
)
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DATA_VARIABLES, DataConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.results.run.view import Run
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter

DOCUMENT = """\
[site]
name = "nancon"
gauge = "NANCON"

[metrics]
window = { start = "2001-01-01", end = "2002-12-31" }

[geographic]
source_mode = "synthetic"

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[calibration]
method = "grid"
max_trials = 3

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
target = "flow.param.K.field.value"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
{observes}
[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["hydrograph"]
"""


def _validate(payload: dict[str, Any]) -> HydroModPyConfig:
    """Validate a payload that declares its DEM under ``[[data.dem.sources]]``."""
    return HydroModPyConfig.model_validate(payload, context={"allow_dem_bootstrap": True})


def _write(tmp_path: Path, observes: str = "") -> Path:
    path = tmp_path / "calage.toml"
    path.write_text(DOCUMENT.replace("{observes}", observes), encoding="utf-8")
    return path


@pytest.mark.unit
def test_a_station_that_is_not_the_gauge_is_refused_with_both_keys(tmp_path) -> None:
    with pytest.raises(ConfigValidationError, match="NANCON") as caught:
        HydroModPyConfig.from_toml(_write(tmp_path, observes='observes = "OTHER"'))

    assert "OTHER" in str(caught.value)


PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "metrics_window_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[metrics]
window = {{ start = "{start}", end = "{end}" }}
"""


def _write_2(tmp_path: Path, *, start: str, end: str) -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(PROJECT_TOML.format(start=start, end=end), encoding="utf-8")
    return config_path


def test_a_root_persistence_key_in_python_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\[simulation\.results\.persistence\]"):
        _validate({"persistence": {"save_zarr": False}})


_HEAD = '[workspace]\n\n[workflow]\nmode = "simulation"\n\n'


_SYNTHETIC = '[geographic]\nsource_mode = "synthetic"\n\n'


def _load(tmp_path: Path, body: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(_HEAD + _SYNTHETIC + body, encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


@pytest.mark.parametrize("solver", ["modflow6", "modflow_nwt"])
@pytest.mark.parametrize("key", ["planar", "grid_dual"])
def test_a_retired_sgrid_key_in_python_is_refused(solver: str, key: str) -> None:
    value = {} if key == "planar" else "voronoi"
    with pytest.raises(ValueError, match=rf"sgrid\.{key} is replaced by \[mesh\]"):
        _validate({"solver": {solver: {"sgrid": {key: value}}}})


def test_the_mesh_section_replaces_them_and_resolves_its_file(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[mesh]\nengine = "voronoi"\ncell_size = 150.0\nriver_cell_size = 25.0\n'
        '[mesh.triangle]\npath = "meshes/catchment.msh"\n'
        '[mesh.voronoi]\nseeds = "triangulation"\n',
    )
    assert cfg.mesh is not None
    assert cfg.mesh.engine == "voronoi"
    assert cfg.mesh.triangle is not None
    assert cfg.mesh.triangle.path == (tmp_path / "meshes" / "catchment.msh").resolve()


def test_the_root_model_declares_the_mesh_in_place_of_the_retired_sections() -> None:
    fields = HydroModPyConfig.model_fields
    assert "mesh" in fields
    assert "mesh_catchment" not in fields
    assert "mesh_input" not in fields
    renamed = fields["mesh"].json_schema_extra
    assert "mesh_catchment" in str(renamed)
    assert "modflow6.sgrid.grid_dual" in str(renamed)


PROJECT_TOML_2 = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[solver]
backend = "{backend}"

[flow]
param_list = ["K", {ids}]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
{params}
"""


PARAM = """
[flow.param.{param_id}.field]
kind = "homogeneous"
value = {value}
"""


PROFILE = """
[flow.param.{param_id}.field_vertical_profile]
kind = "exponential"
characteristic_depth = "15 m"
"""


def _load_2(
    tmp_path: Path,
    values: dict[str, str],
    *,
    backend: str = "modflow6",
    profile_on: str | None = None,
) -> HydroModPyConfig:
    params = "".join(
        PARAM.format(param_id=param_id, value=value) for param_id, value in values.items()
    )
    if profile_on is not None:
        params += PROFILE.format(param_id=profile_on)
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML_2.format(
            backend=backend,
            ids=", ".join(f'"{param_id}"' for param_id in values),
            params=params,
        ),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


TENSOR = {"K22": '"2e-6 m/s"', "angle1": "30.0", "angle2": "-20.0", "angle3": "5.0"}


def test_modflow_nwt_refuses_k22(tmp_path: Path) -> None:
    with pytest.raises(IncompatibleCapabilitiesError, match="flow.param.K22"):
        _load_2(tmp_path, {"K22": '"2e-6 m/s"'}, backend="modflow_nwt")


def test_an_angle_with_a_vertical_profile_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="scale the angle with depth"):
        _load_2(tmp_path, {"angle1": "30.0"}, profile_on="angle1")


# A sealed config whose ``[metrics] window`` misses its run still reads.
#
# A file the user loads is refused when its window shares no day with the run.
# A run sealed before that refusal existed carries such a window (example 04,
# ``nancon_api_daily`` of 2026-10-16): re-reading it for a rerun or for
# ``Run.hydromodpy_config`` warns and keeps the run, which has no score.


SEALED = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "sealed_window_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[metrics]
window = { start = "2001-01-01", end = "2002-12-31" }
"""


def _snapshot() -> dict:
    return tomllib.loads(SEALED)


@pytest.mark.unit
def test_a_user_document_with_the_window_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"\[metrics\] window"):
        HydroModPyConfig.from_dict(_snapshot(), base_dir=tmp_path)


@pytest.mark.unit
def test_a_snapshot_reads_with_a_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        cfg = HydroModPyConfig.from_snapshot(_snapshot())

    assert cfg.metrics.window.start.isoformat() == "2001-01-01"
    assert "shares no day" in caplog.text


@pytest.mark.unit
def test_a_sealed_run_rebuilds_its_config(monkeypatch, caplog, tmp_path: Path) -> None:
    snapshot = _snapshot()
    monkeypatch.setattr(Run, "config_snapshot", property(lambda self: snapshot))
    run = Run.__new__(Run)
    run._sim_id = "0123456789abcdef"
    run._read_config = lambda payload: HydroModPyConfig.from_dict(
        payload, base_dir=tmp_path, sealed=True
    )

    with caplog.at_level(logging.WARNING):
        cfg = run.hydromodpy_config

    assert cfg.metrics.window.end.isoformat() == "2002-12-31"
    assert "shares no day" in caplog.text


# A layering by surfaces is checked when the project file is read.
#
# Its rasters and ``[data.layer_base]`` name the same bases, MODFLOW-NWT reads it
# only when a thin layer keeps its minimum thickness, and a vertical profile of K
# on fewer than five layers is warned about.


PROJECT_TOML_3 = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[solver]
backend = "{backend}"

[domain.layers]
{layers}

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
{profile}
{data}
"""


SURFACES = """genmtd_lay = "surfaces"
pinch_out = "{pinch_out}"

[[domain.layers.layer]]
name = "weathered"
surface = "weathered_base"

[[domain.layers.layer]]
name = "rock"
"""


LAYER_BASE = """
[[data.layer_base.sources]]
name = "{name}"
path = "weathered.tif"
"""


PROFILE_2 = """
[flow.param.K.field_vertical_profile]
kind = "exponential"
characteristic_depth = "15 m"
"""


def _load_3(
    tmp_path: Path,
    *,
    backend: str = "modflow6",
    pinch_out: str = "pass_through",
    base_name: str | None = "weathered_base",
    layers: str | None = None,
    profile: str = "",
) -> HydroModPyConfig:
    (tmp_path / "weathered.tif").touch()
    path = tmp_path / "project.toml"
    path.write_text(
        PROJECT_TOML_3.format(
            backend=backend,
            layers=layers or SURFACES.format(pinch_out=pinch_out),
            profile=profile,
            data="" if base_name is None else LAYER_BASE.format(name=base_name),
        ),
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


def test_a_base_surface_no_data_declares_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"does not declare them"):
        _load_3(tmp_path, base_name=None)


def test_a_declared_base_no_layer_reads_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"no layer of \[domain.layers\] reads"):
        _load_3(tmp_path, base_name="other_base", layers='genmtd_lay = "constant"\nnlay = 2')


# A mesh along the rivers needs a river network threshold, named at check time.
#
# The mesh switches [geographic.river_network] on by itself, so the threshold
# check of that section never ran, and the run stopped at build_geographic
# with "threshold_area_km2 must be > 0". The refusal names what switched the
# network on: the river family, or a refinement zone on height_above_stream.


def _payload(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem"}},
        "data": {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}},
        "mesh": {"engine": "voronoi"},
    }
    payload.update(sections)
    return payload


def test_a_cells_threshold_is_named_in_cells_mode() -> None:
    payload = _payload()
    payload["geographic"]["river_network"] = {"threshold_mode": "cells"}
    with pytest.raises(ValueError, match="Set threshold_cells under"):
        _validate(payload)


def _above_stream_zone() -> dict[str, Any]:
    return {"where": "height_above_stream", "below": 2.0, "cell_size": 25.0}


def test_a_height_zone_with_a_threshold_loads() -> None:
    payload = _payload(
        mesh={
            "engine": "voronoi",
            "families": {"rivers": "none"},
            "refinement_zone": [_above_stream_zone()],
        }
    )
    payload["geographic"]["river_network"] = {"threshold_area_km2": 0.5}
    cfg = _validate(payload)
    assert cfg.mesh.refines_above_stream()


def test_a_stream_boundary_on_a_mesh_read_from_a_file_names_the_file() -> None:
    mesh = {"engine": "triangle", "triangle": {"path": "mesh/catchment.msh"}}
    with pytest.raises(ValueError) as excinfo:
        _validate(_payload(mesh=mesh, flow={"bc": {"stream": {}}}))
    message = str(excinfo.value)
    assert "The 'stream' boundary on a [mesh.triangle] path mesh" in message
    assert "Set threshold_area_km2 under [geographic.river_network]" in message


# A lake in soil mode only sees the water the stream network routes to it.
#
# The soil reservoir sends its recharge to the aquifer through drains, not
# through a direct lake package: without a ``[flow.sinks_sources.sfr]`` network, a
# lake would never receive any of it.


SOIL_PROJECT_TOML = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "soil_config_test"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[data]
types = ["precipitation", "etp"]

[[data.precipitation.sources]]
source = "sim2"
extent = "watershed"

[[data.etp.sources]]
source = "sim2"
extent = "watershed"

[flow]
first_period_steady = false

[flow.ic]
kind = "steady_state"

[flow.bc.drainage]

[flow.sinks_sources.etp]

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
{tables}
"""


LAKE = """
[flow.sinks_sources.lakes.pond]
bedleak = 1e-6
initial_stage = "10 m"
"""


def _write_3(tmp_path: Path, tables: str = "") -> Path:
    config_path = tmp_path / "project.toml"
    config_path.write_text(SOIL_PROJECT_TOML.format(tables=tables), encoding="utf-8")
    return config_path


def test_a_lake_without_a_network_is_refused(tmp_path: Path) -> None:
    config_path = _write_3(tmp_path, LAKE)

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert (
        "[flow.sinks_sources.lakes] declares a lake with no stream network: in soil "
        "mode the water that seeps out of the ground reaches a lake only through the "
        "stream network, so the lake would receive none of it. Declare a "
        "[flow.sinks_sources.sfr] network, or remove [flow.sinks_sources.recharge.soil] "
        "and load [data.runoff] as before."
    ) in str(excinfo.value)


def test_a_lake_with_a_network_loads(tmp_path: Path) -> None:
    config_path = _write_3(tmp_path, LAKE + "[flow.sinks_sources.sfr.main]\n")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert {"lake", "sfr"} <= set(cfg.flow.active_bc)


def _write_with_network(tmp_path: Path, network_lines: str) -> Path:
    return _write_3(tmp_path, LAKE + "[flow.sinks_sources.sfr.main]\n" + network_lines)


def test_route_drainage_is_on_by_default() -> None:
    from hydromodpy.model.sinks_sources.sfr import FlowReachNetworkConfig

    assert FlowReachNetworkConfig.model_fields["route_drainage"].default is True


def test_a_lake_in_soil_mode_refuses_route_drainage_off(tmp_path: Path) -> None:
    config_path = _write_with_network(tmp_path, "route_drainage = false\n")

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(config_path)

    assert "route_drainage = false with a lake" in str(excinfo.value)


def test_a_lake_in_soil_mode_accepts_the_default_route_drainage(tmp_path: Path) -> None:
    config_path = _write_with_network(tmp_path, "")

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.flow.sinks_sources.sfr["main"].route_drainage is True


# A solver paired with a mesh engine it cannot read is refused while the file loads.
#
# The check runs before any step, so a NWT run with ``engine = "voronoi"`` never
# reaches the geographic step. The refusal names the solver and the engine.


def _payload_2(solver: str, mesh: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": solver},
    }
    if mesh is not None:
        payload["mesh"] = mesh
    return payload


# Boussinesq refuses a layering it would ignore.
#
# Boussinesq solves one layer over the whole aquifer: it leaves ``layers`` out of
# its ``supports``. A file, a calibration phase or an older solver table that asks
# it for more than one layer, or for layers by surfaces, is refused when it is
# read. A sealed run is read as it was run, with a warning. The adapter refuses it
# again at the solve, for a layering assigned after the load.


PROJECT_TOML_4 = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["{solver}"]

[mesh]
engine = "triangle"

[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
{extra}
"""


CALIBRATION = """
[calibration]
method = "grid"

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
path = "flow.param.K.field.value"

[[calibration.phases]]
name = "deep"
parameters = ["K"]

[calibration.phases.overrides]
{overrides}
"""


SURFACES_2 = """
[domain.layers]
genmtd_lay = "surfaces"

[[domain.layers.layer]]
name = "weathered"
depth = 15.0

[[domain.layers.layer]]
name = "rock"
"""


PROFILE_3 = """
[flow.param.K.field_vertical_profile]
kind = "exponential"
characteristic_depth = "15 m"
"""


IGNORED = "it would be ignored without a word"
HONORED = "run a flow solver that honors it (modflow6, modflow_nwt)"


def _write_4(tmp_path: Path, extra: str = "", *, solver: str = "boussinesq") -> Path:
    path = tmp_path / "project.toml"
    path.write_text(PROJECT_TOML_4.format(solver=solver, extra=extra), encoding="utf-8")
    return path


def _load_4(tmp_path: Path, extra: str = "", *, solver: str = "boussinesq") -> HydroModPyConfig:
    return HydroModPyConfig.from_toml(_write_4(tmp_path, extra, solver=solver))


def test_a_phase_that_asks_for_layers_is_refused(tmp_path: Path) -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        _load_4(tmp_path, CALIBRATION.format(overrides='"domain.layers.nlay" = 3'))

    message = str(excinfo.value)
    assert (
        "does not honor the domain.layers override of calibration phase 'deep' "
        f"(genmtd_lay = 'constant', 3 layer(s)): {IGNORED}"
    ) in message


@pytest.mark.unit
def test_a_phase_that_keeps_one_layer_loads(tmp_path: Path) -> None:
    cfg = _load_4(tmp_path, CALIBRATION.format(overrides='"domain.layers.nodata" = -1.0'))

    assert cfg.calibration.phases[0].overrides == {"domain.layers.nodata": -1.0}


@pytest.mark.unit
def test_a_k_profile_says_boussinesq_reads_one_k_per_column(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        _load_4(tmp_path, PROFILE_3)

    assert "boussinesq solves one layer and reads one K per column" in caplog.text
    assert "at least five layers" not in caplog.text


@pytest.mark.unit
def test_the_adapter_refuses_a_layering_assigned_after_the_load() -> None:
    # The model's domain is built from ``cfg.domain`` when the run is prepared, so
    # a layering assigned on the config after the load reaches the adapter here.
    layers = VerticalGridConfig(nlay=3)
    domain = SimpleNamespace(config=SimpleNamespace(layers=layers))
    model = SimpleNamespace(geometry=SimpleNamespace(domain=domain))

    with pytest.raises(ConfigError, match=r"builds 3 layer\(s\) .*which it would ignore"):
        BoussinesqFlowAdapter().build(model, None, RunSlot(Path("unused"), "island"), None)


# Cross-section coherence checks on :class:`HydroModPyConfig`.
#
# The architecture spec (``02_config_pydantic.md`` §3.2) calls for a
# cross-section validator firing after individual sub-configs validate.


def _minimal_geographic() -> GeographicConfig:
    """Build a minimal synthetic geographic section for test scaffolding."""
    return GeographicConfig(source_mode="synthetic")


def _base_kwargs(tmp_path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": _minimal_geographic(),
    }


def test_data_inference_strict_without_types_is_rejected(tmp_path) -> None:
    bad_data = DataConfig(types=[], inference_mode="strict")
    with pytest.raises(ValidationError) as excinfo:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            data=bad_data,
        )
    assert "inference_mode='strict'" in str(excinfo.value)


def test_a_raster_depth_model_without_a_substratum_is_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError, match=r"\[data.substratum\]"):
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            domain={"depth_model": {"kind": "raster_substratum"}},
        )


def test_a_raster_depth_model_with_a_substratum_is_accepted(tmp_path) -> None:
    from hydromodpy.data.variables.user_rasters import SubstratumConfig

    raster = tmp_path / "substratum.tif"
    raster.write_bytes(b"")
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        domain={"depth_model": {"kind": "raster_thickness", "scale": 1.5}},
        data=DataConfig(substratum=SubstratumConfig.from_raster(raster)),
    )

    assert cfg.domain.depth_model.scale == 1.5


def test_the_overview_workflow_without_an_overview_section_is_rejected(tmp_path) -> None:
    kwargs = _base_kwargs(tmp_path)
    kwargs["workflow"] = {"mode": "overview"}

    with pytest.raises(ValidationError, match=r"needs an \[overview\] section"):
        HydroModPyConfig(**kwargs)


# ``[geographic.capped_breach]`` sets the limits of ``capped_breach``, and only of it.


def _config(**overrides) -> GeographicConfig:
    return GeographicConfig(source_mode="synthetic", **overrides)


def test_the_section_without_a_method_is_refused() -> None:
    with pytest.raises(ValidationError, match="capped_breach"):
        _config(capped_breach={"max_depth": 1.0})


def test_a_sealed_config_reads_back_what_it_wrote() -> None:
    for config in (_config(), _config(dem_correc_type="capped_breach")):
        assert GeographicConfig.model_validate(config.model_dump(mode="json")) == config


def test_the_description_names_the_three_methods_and_what_each_changes() -> None:
    description = GeographicConfig.model_fields["dem_correc_type"].description or ""

    for method in ("'fill'", "'breach'", "'capped_breach'"):
        assert method in description
    assert "only raises" in description
    assert "mostly lowers" in description
    assert "raising single-cell pits" in description
    assert "lowers and raises" in description
    assert "[geographic.capped_breach]" in description


# [data] TOML wiring for the lake families: typed sections + path resolution.
#
# Guards that ``[data.lake_*]`` sections validate into the
# dedicated typed configs through ``DataConfig.from_toml_section`` and
# that ``InputFile``-annotated paths are resolved relative to the TOML dir.


def test_lake_families_are_supported_manager_types() -> None:
    for name in ("lake_abacus", "lake_bathymetry", "lake_geometry", "lake_levels"):
        assert name in DATA_VARIABLES


@pytest.mark.unit
@pytest.mark.parametrize("declares", [True, False], ids=["with-a-dem-source", "without"])
def test_a_mapping_reads_a_dem_catchment_from_its_dem_source(tmp_path, declares) -> None:
    # A Python caller passes no validation context: the root reads the rule from
    # the mapping, as the file loader does.
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "dem.tif").write_bytes(b"")
    payload: dict[str, Any] = {
        "workspace": {"project_root": str(tmp_path)},
        "site": {"name": "probe"},
        "geographic": {"catchment": {"kind": "dem"}},
    }
    if declares:
        payload["data"] = {
            "types": ["dem"],
            "dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]},
        }
        assert HydroModPyConfig.model_validate(payload).geographic.catchment.kind == "dem"
    else:
        with pytest.raises(ValidationError, match=r"\[\[data\.dem\.sources\]\]"):
            HydroModPyConfig.model_validate(payload)
