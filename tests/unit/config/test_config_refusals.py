"""Checks ``HydroModPyConfig`` makes while a file or a mapping is read.

A file that cannot run is refused before any step, with the key to write instead.
Lengths are in m, areas in km2, the run window in days. A sealed run, read back as
it was run, warns where a user file is refused.
"""

from __future__ import annotations

import logging
import tomllib
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import hydromodpy
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigValidationError,
    IncompatibleCapabilitiesError,
)
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DATA_VARIABLES, DataConfig
from hydromodpy.data.variables.user_rasters import SubstratumConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.model import ModelTime, model_from_flow
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.run.view import Run
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.base.registry import solvers
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.solver_contract import assert_supported_runtime_subset
from tests._helpers.fake_solvers import fake_adapter
from tests._helpers.model_factory import default_options, small_geometry


def validate(payload: dict[str, Any]) -> HydroModPyConfig:
    """Validate a mapping that declares its DEM under ``[[data.dem.sources]]``."""
    return HydroModPyConfig.model_validate(payload, context={"allow_dem_bootstrap": True})


def payload_of(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem"}},
        "data": {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}},
    }
    payload.update(sections)
    return payload


def flow_on(solver: str) -> dict[str, Any]:
    return {"process": [{"id": "flow_main", "kind": "flow", "solvers": [solver]}]}


def mesh_payload(
    mesh: dict[str, Any] | None,
    *,
    well: dict[str, Any] | None = None,
    reach: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sinks: dict[str, Any] = {}
    if well is not None:
        sinks["wells"] = {"W1": {"location": well, "flux": -1.0}}
    if reach is not None:
        sinks["sfr"] = {"net": {"reaches": [reach]}}
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": "modflow6"},
        "flow": {"sinks_sources": sinks},
    }
    if mesh is not None:
        payload["mesh"] = mesh
    return payload


def base_kwargs(tmp_path: Path) -> dict[str, Any]:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


# A project file: this head, then the tables of one case.
HEAD = """
[workflow]
mode = "simulation"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"
"""

K_FLOW = """
[flow]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"
"""

VERTICAL_PROFILE = """
[flow.param.{param}.field_vertical_profile]
kind = "exponential"
characteristic_depth = "15 m"
"""

# Layers by surfaces: a base surface named by the layer and by [[data.layer_base.sources]].
SURFACES = """
[domain.layers]
genmtd_lay = "surfaces"
pinch_out = "pass_through"

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

# Boussinesq solves one layer, so it leaves layers out of its supports.
BOUSSINESQ = """
[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["boussinesq"]

[mesh]
engine = "triangle"
"""

PHASE = """
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


def load(tmp_path: Path, body: str) -> HydroModPyConfig:
    (tmp_path / "weathered.tif").touch()
    path = tmp_path / "project.toml"
    path.write_text(HEAD + body, encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


# The metrics window misses the run: 2001-2002 against 2015-2020. A sealed run
# written before the refusal existed (example 04, 2026-10-16) still has such a window.
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

CALIBRATION_DOCUMENT = """\
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
observes = "OTHER"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["hydrograph"]
"""

# A [lay, row, col] address needs a mesh with rows: only the regular engine has them.
CELL = {"kind": "cell", "cell": [0, 1, 2]}
XY = {"kind": "absolute_xy", "x": 1.0, "y": 2.0}
REACH = {"cell": CELL, "length": "100 m", "width": "2 m", "slope": 0.001, "top": "10 m"}


def test_station_other_than_the_gauge(tmp_path: Path) -> None:
    path = tmp_path / "calage.toml"
    path.write_text(CALIBRATION_DOCUMENT, encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="NANCON") as caught:
        HydroModPyConfig.from_toml(path)

    assert "OTHER" in str(caught.value)


def test_scalar_workflow_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "scalar_workflow.toml"
    path.write_text(
        'workflow = "simulation"\n\n[workspace]\n\n[geographic]\nsource_mode = "synthetic"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match=r"\[workflow\]"):
        HydroModPyConfig.from_toml(path)


def test_workspace_path_tokens_are_refused(tmp_path: Path) -> None:
    drive_token = chr(0xF03A)
    separator_token = chr(0xF05C)
    encoded_path = (
        f"C{drive_token}{separator_token}codes{separator_token}HydroModPy{separator_token}outputs"
    )

    with pytest.raises(ConfigValidationError, match="encoded as a safe filename"):
        HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "simulation"},
                "workspace": {"root": encoded_path},
                "geographic": {"source_mode": "synthetic"},
            },
            base_dir=tmp_path,
        )


def test_mesh_section_resolves_its_file(tmp_path: Path) -> None:
    cfg = load(
        tmp_path,
        '[mesh]\nengine = "voronoi"\ncell_size = 150.0\nriver_cell_size = 25.0\n'
        '[mesh.triangle]\npath = "meshes/catchment.msh"\n'
        '[mesh.voronoi]\nseeds = "triangulation"\n',
    )

    assert cfg.mesh is not None
    assert cfg.mesh.engine == "voronoi"
    assert cfg.mesh.triangle is not None
    assert cfg.mesh.triangle.path == (tmp_path / "meshes" / "catchment.msh").resolve()


def test_mesh_replaces_the_retired_sections() -> None:
    fields = HydroModPyConfig.model_fields
    assert "mesh" in fields
    assert "mesh_catchment" not in fields
    assert "mesh_input" not in fields
    renamed = fields["mesh"].json_schema_extra
    assert "mesh_catchment" in str(renamed)
    assert "modflow6.sgrid.grid_dual" in str(renamed)


def test_nwt_zonal_top_without_a_channel_source_loads(tmp_path: Path) -> None:
    cfg = load(
        tmp_path,
        '[solver.modflow_nwt.sgrid.top_sampling]\nmode = "zonal"\nchannel_source = "none"\n',
    )

    assert cfg.solver.options_of("modflow_nwt").sgrid.top_sampling.mode == "zonal"


def test_plugin_flow_solver_is_accepted(tmp_path: Path, isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("pluginflow"))

    cfg = HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        simulation=flow_on("pluginflow"),
        flow=FlowConfig(bc={}),
    )

    assert cfg.solver.backend_name == "pluginflow"


def test_written_backend_refuses_a_later_flow_solver() -> None:
    from hydromodpy.solver.base.simulation_config import SimulationConfig

    cfg = validate(payload_of(simulation=flow_on("modflow6"), solver={"backend": "modflow6"}))

    with pytest.raises(ValidationError, match="must name the same solver"):
        cfg.simulation = SimulationConfig.model_validate(flow_on("modflow_nwt"))


def test_boussinesq_refuses_a_lake() -> None:
    lakes = {"lac0": {"bedleak": 0.1, "initial_stage": "85 m"}}
    flow = Flow(FlowConfig(sinks_sources={"lakes": lakes}))
    model = model_from_flow(
        flow,
        geometry=small_geometry(),
        time=ModelTime.from_flow(flow, None),
        options=default_options(),
    )

    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        assert_supported_runtime_subset(model, solvers.get("flow", "boussinesq").supports)

    assert "lake" in str(excinfo.value)
    assert excinfo.value.code == "HMPY.E407"


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_well_by_coordinates_loads_on_every_engine(engine: str) -> None:
    HydroModPyConfig.model_validate(mesh_payload({"engine": engine}, well=XY))


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_reach_by_row_and_column_is_refused(engine: str) -> None:
    with pytest.raises(ValueError, match=r"flow\.sinks_sources\.sfr\.net\.reaches\[0\]\.cell"):
        HydroModPyConfig.model_validate(mesh_payload({"engine": engine}, reach=REACH))


def test_every_cell_address_is_named_at_once() -> None:
    payload = mesh_payload({"engine": "triangle"}, well=CELL, reach=REACH)

    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(payload)

    message = str(excinfo.value)
    assert "wells.W1.location" in message
    assert "sfr.net.reaches[0].cell" in message


def test_height_zone_with_a_threshold_loads() -> None:
    zone = {"where": "height_above_stream", "below": 2.0, "cell_size": 25.0}
    cfg = validate(
        payload_of(
            mesh={"engine": "voronoi", "families": {"rivers": "none"}, "refinement_zone": [zone]},
            geographic={"catchment": {"kind": "dem"}, "river_network": {"threshold_area_km2": 0.5}},
        )
    )

    assert cfg.mesh.refines_above_stream()


def test_stream_boundary_on_a_mesh_file_names_the_file() -> None:
    mesh = {"engine": "triangle", "triangle": {"path": "mesh/catchment.msh"}}

    with pytest.raises(ValueError) as excinfo:
        validate(payload_of(mesh=mesh, flow={"bc": {"stream": {}}}))

    message = str(excinfo.value)
    assert "The 'stream' boundary on a [mesh.triangle] path mesh" in message
    assert "Set threshold_area_km2 under [geographic.river_network]" in message


def test_user_document_with_a_missed_window_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"\[metrics\] window"):
        HydroModPyConfig.from_dict(tomllib.loads(SEALED), base_dir=tmp_path)


def test_date_window_includes_both_ends() -> None:
    window = DateWindow(start=date(2016, 1, 1), end=date(2017, 12, 31))

    assert window.contains(date(2016, 1, 1)) and window.contains(date(2017, 12, 31))
    assert not window.contains(date(2018, 1, 1))


def test_root_package_refuses_an_unknown_name() -> None:
    name = "not_a_name"

    with pytest.raises(AttributeError, match=f"no attribute '{name}'"):
        getattr(hydromodpy, name)


def test_window_inside_the_run_loads(tmp_path: Path) -> None:
    document = tomllib.loads(SEALED)
    document["metrics"]["window"] = {"start": "2016-01-01", "end": "2017-12-31"}

    cfg = HydroModPyConfig.from_dict(document, base_dir=tmp_path)

    assert cfg.metrics.window.end.isoformat() == "2017-12-31"


def test_snapshot_with_a_missed_window_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        cfg = HydroModPyConfig.from_snapshot(tomllib.loads(SEALED))

    assert cfg.metrics.window.start.isoformat() == "2001-01-01"
    assert "shares no day" in caplog.text


def test_sealed_run_rebuilds_its_config(monkeypatch, caplog, tmp_path: Path) -> None:
    snapshot = tomllib.loads(SEALED)
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


def test_boussinesq_phase_with_one_layer_loads(tmp_path: Path) -> None:
    cfg = load(
        tmp_path, BOUSSINESQ + K_FLOW + PHASE.format(overrides='"domain.layers.nodata" = -1.0')
    )

    assert cfg.calibration.phases[0].overrides == {"domain.layers.nodata": -1.0}


def test_k_profile_warns_that_boussinesq_reads_one_k(tmp_path: Path, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        load(tmp_path, BOUSSINESQ + K_FLOW + VERTICAL_PROFILE.format(param="K"))

    assert "boussinesq solves one layer and reads one K per column" in caplog.text
    assert "at least five layers" not in caplog.text


def test_boussinesq_adapter_refuses_layers_set_after_the_load() -> None:
    # The domain is built from ``cfg.domain`` when the run is prepared, so a
    # layering assigned on the config after the load reaches the adapter here.
    layers = VerticalGridConfig(nlay=3)
    domain = SimpleNamespace(config=SimpleNamespace(layers=layers))
    model = SimpleNamespace(geometry=SimpleNamespace(domain=domain))

    with pytest.raises(ConfigError, match=r"builds 3 layer\(s\) .*which it would ignore"):
        BoussinesqFlowAdapter().build(model, None, RunSlot(Path("unused"), "island"), None)


def test_raster_depth_with_a_substratum_loads(tmp_path: Path) -> None:
    raster = tmp_path / "substratum.tif"
    raster.write_bytes(b"")

    cfg = HydroModPyConfig(
        **base_kwargs(tmp_path),
        domain={"depth_model": {"kind": "raster_thickness", "scale": 1.5}},
        data=DataConfig(substratum=SubstratumConfig.from_raster(raster)),
    )

    assert cfg.domain.depth_model.scale == 1.5


def geographic(**overrides: Any) -> GeographicConfig:
    return GeographicConfig(source_mode="synthetic", **overrides)


def test_capped_breach_section_needs_its_method() -> None:
    with pytest.raises(ValidationError, match="capped_breach"):
        geographic(capped_breach={"max_depth": 1.0})


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(geographic(), id="default"),
        pytest.param(geographic(dem_correc_type="capped_breach"), id="capped breach"),
    ],
)
def test_sealed_geographic_reads_back(config: GeographicConfig) -> None:
    assert GeographicConfig.model_validate(config.model_dump(mode="json")) == config


def test_dem_correction_description_names_the_methods() -> None:
    description = GeographicConfig.model_fields["dem_correc_type"].description or ""

    for method in ("'fill'", "'breach'", "'capped_breach'"):
        assert method in description
    assert "only raises" in description
    assert "mostly lowers" in description
    assert "raising single-cell pits" in description
    assert "lowers and raises" in description
    assert "[geographic.capped_breach]" in description


@pytest.mark.parametrize("name", ["lake_abacus", "lake_bathymetry", "lake_geometry", "lake_levels"])
def test_lake_families_are_data_variables(name: str) -> None:
    assert name in DATA_VARIABLES


@pytest.mark.unit
@pytest.mark.parametrize("declares", [True, False], ids=["with a dem source", "without"])
def test_dem_catchment_reads_its_dem_source(tmp_path, declares: bool) -> None:
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


TRANSPORT_UNDER_BOUSSINESQ = {
    "process": [
        {"id": "flow_main", "kind": "flow", "solvers": ["boussinesq"]},
        {"id": "particles", "kind": "transport", "solvers": ["modpath"]},
    ]
}

PAYLOAD_REFUSALS = [
    pytest.param(
        {"persistence": {"save_zarr": False}},
        ValueError,
        r"\[simulation\.results\.persistence\]",
        id="root persistence key",
    ),
    pytest.param(
        {"solver": {"modflow6": {"sgrid": {"planar": {}}}}},
        ValueError,
        r"sgrid\.planar is replaced by \[mesh\]",
        id="mf6 sgrid planar",
    ),
    pytest.param(
        {"solver": {"modflow6": {"sgrid": {"grid_dual": "voronoi"}}}},
        ValueError,
        r"sgrid\.grid_dual is replaced by \[mesh\]",
        id="mf6 sgrid grid_dual",
    ),
    pytest.param(
        {"solver": {"modflow_nwt": {"sgrid": {"planar": {}}}}},
        ValueError,
        r"sgrid\.planar is replaced by \[mesh\]",
        id="nwt sgrid planar",
    ),
    pytest.param(
        {"solver": {"modflow_nwt": {"sgrid": {"grid_dual": "voronoi"}}}},
        ValueError,
        r"sgrid\.grid_dual is replaced by \[mesh\]",
        id="nwt sgrid grid_dual",
    ),
    pytest.param(
        payload_of(simulation=flow_on("modflow_nwt"), solver={"backend": "modflow6"}),
        ValidationError,
        "must name the same solver",
        id="two keys, two solvers",
    ),
    pytest.param(
        payload_of(simulation=TRANSPORT_UNDER_BOUSSINESQ),
        IncompatibleCapabilitiesError,
        r"the transport solver 'modpath' reads face_flow, and solver.backend = 'boussinesq'",
        id="transport under boussinesq",
    ),
    pytest.param(
        {
            "geographic": {"source_mode": "synthetic"},
            "metrics": {"window": {"start": "2002-01-01", "end": "2001-01-01"}},
        },
        ValidationError,
        "before it starts",
        id="reversed metrics window",
    ),
    # A mesh along the rivers switches the network on, the threshold must be named.
    pytest.param(
        payload_of(
            mesh={"engine": "voronoi"},
            geographic={
                "catchment": {"kind": "dem"},
                "river_network": {"threshold_mode": "cells"},
            },
        ),
        ValueError,
        "Set threshold_cells under",
        id="threshold in cells",
    ),
]

TOML_REFUSALS = [
    pytest.param(
        '[solver]\nbackend = "modflow_nwt"\n\n[flow]\nparam_list = ["K", "K22"]\n'
        '\n[flow.param.K.field]\nkind = "homogeneous"\nvalue = "1e-5 m/s"\n'
        '\n[flow.param.K22.field]\nkind = "homogeneous"\nvalue = "2e-6 m/s"\n',
        IncompatibleCapabilitiesError,
        "flow.param.K22",
        id="nwt reads no K22",
    ),
    pytest.param(
        '[solver]\nbackend = "modflow6"\n\n[flow]\nparam_list = ["K", "angle1"]\n'
        '\n[flow.param.K.field]\nkind = "homogeneous"\nvalue = "1e-5 m/s"\n'
        '\n[flow.param.angle1.field]\nkind = "homogeneous"\nvalue = 30.0\n'
        + VERTICAL_PROFILE.format(param="angle1"),
        ConfigValidationError,
        "scale the angle with depth",
        id="angle with a vertical profile",
    ),
    pytest.param(
        '[solver.modflow_nwt.sgrid.top_sampling]\nmode = "zonal"\n',
        ConfigValidationError,
        "MODFLOW-NWT does not read the channel tree",
        id="nwt zonal top with a channel source",
    ),
    pytest.param(
        '[solver]\nbackend = "modflow6"\n' + SURFACES + K_FLOW,
        ConfigValidationError,
        "does not declare them",
        id="base surface not declared",
    ),
    pytest.param(
        '[solver]\nbackend = "modflow6"\n\n[domain.layers]\ngenmtd_lay = "constant"\nnlay = 2\n'
        + K_FLOW
        + LAYER_BASE.format(name="other_base"),
        ConfigValidationError,
        r"no layer of \[domain.layers\] reads",
        id="declared base not read",
    ),
    pytest.param(
        BOUSSINESQ + K_FLOW + PHASE.format(overrides='"domain.layers.nlay" = 3'),
        IncompatibleCapabilitiesError,
        r"does not honor the domain.layers override of calibration phase 'deep' "
        r"\(genmtd_lay = 'constant', 3 layer\(s\)\): it would be ignored without a word",
        id="boussinesq phase asks for layers",
    ),
]

ROOT_REFUSALS = [
    pytest.param(
        {"data": DataConfig(types=[], inference_mode="strict")},
        "inference_mode='strict'",
        id="strict inference without types",
    ),
    pytest.param(
        {"domain": {"depth_model": {"kind": "raster_substratum"}}},
        r"\[data.substratum\]",
        id="raster depth without a substratum",
    ),
    pytest.param(
        {"workflow": {"mode": "overview"}},
        r"needs an \[overview\] section",
        id="overview without its section",
    ),
]


@pytest.mark.parametrize(("payload", "error", "message"), PAYLOAD_REFUSALS)
def test_payload_refusals(payload: dict[str, Any], error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message):
        validate(payload)


@pytest.mark.parametrize(("body", "error", "message"), TOML_REFUSALS)
def test_file_refusals(tmp_path: Path, body: str, error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message):
        load(tmp_path, body)


@pytest.mark.parametrize(("overrides", "message"), ROOT_REFUSALS)
def test_root_refusals(tmp_path: Path, overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        HydroModPyConfig(**(base_kwargs(tmp_path) | overrides))
