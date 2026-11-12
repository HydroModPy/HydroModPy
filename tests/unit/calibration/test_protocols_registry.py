"""Registry of calibration protocols: expansion of a declaration into stages.

A protocol name or table expands into phases and objective blocks. The frozen
config.toml of a run must read back as its own protocol, with the metrics window
(dates) reaching the transient stage. Legacy single-metric stages are folded.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import apply_project_defaults
from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.protocols import registry
from hydromodpy.calibration.protocols.registry import expand_calibration_protocol
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.data.loading.inputs import ResolvedInputs
from hydromodpy.results.storage.contract import RUN_SEARCH_TABLE
from hydromodpy.workflow.solution_key import request_id_of
from hydromodpy.workflow.steps.prepare_solver.freeze import (
    frozen_config_of,
    portable_config_document,
    search_of,
)
from hydromodpy.workflow.steps.prepare_solver.resolved import config_drift, resolved_config_document
from tests.unit.calibration._factories_scoring import make_document

PROJECT = """\
[site]
name = "nancon"
gauge = "NANCON"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["hydrography", "hydrometry"]

[[data.hydrography.sources]]
source = "file"
path = "inputs/nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "file"
path = "inputs/hydrometry"
station_ids = ["NANCON"]

[simulation.time]
start_datetime = "{start}"
end_datetime = "{end}"
step_value = 1
step_unit = "month"

[metrics.window]
start = "{start}"
end = "{end}"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
map.complete = "inputs/nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
"""


def _project(root: Path, *, start: str, end: str) -> Path:
    project = root / "projects" / "nancon"
    inputs = project / "inputs"
    (inputs / "hydrometry").mkdir(parents=True)
    (inputs / "nancon_stream_network.gpkg").write_bytes(b"x")
    text = PROJECT.format(start=start, end=end)
    (project / "project.toml").write_text(text, encoding="utf-8")
    return project


def _frozen(project: Path) -> Path:
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    path = run_dir / "config.toml"
    path.write_text(portable_config_document(cfg, run_dir, project), encoding="utf-8")
    return path


SEALED_STAGE_REFUSALS = [
    pytest.param(1, "window", {"start": "2002-01-01"}, "phases", id="stage names another window"),
    # Only a pre-release sealed a station in a stage. The read names the key and stops.
    pytest.param(
        0,
        "observed_station_id",
        "OTHER",
        r"calibration\.phases\[0\]\.observed_station_id, written by a pre-release",
        id="station sealed in a stage",
    ),
]


@pytest.mark.parametrize(("index", "key", "value", "match"), SEALED_STAGE_REFUSALS)
def test_frozen_stage_refusals(tmp_path: Path, index, key, value, match) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    document = tomllib.loads(_frozen(project).read_text(encoding="utf-8"))
    document["calibration"]["phases"][index][key] = value

    with pytest.raises(ConfigValidationError, match=match):
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})


def test_calibration_run_seals_its_own_solve(tmp_path: Path) -> None:
    """A replay solves once. The search stays beside the run, for what redraws its criterion."""
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    ctx = SimpleNamespace(cfg=cfg, run_dir=run_dir, setup=SimpleNamespace(domain=None))

    frozen = frozen_config_of(ctx)
    path = run_dir / "config.toml"
    path.write_text(portable_config_document(frozen, run_dir, project), encoding="utf-8")
    (run_dir / "config.resolved.toml").write_text(
        resolved_config_document(frozen, project, search=search_of(cfg, run_dir, project)),
        encoding="utf-8",
    )

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    assert "calibration" not in document
    assert document["workflow"]["mode"] == "simulation"
    replay = HydroModPyConfig.from_toml(path)
    assert replay.calibration is None

    def asked(config: HydroModPyConfig, *, search: bool) -> str:
        return request_id_of(config, ResolvedInputs(), search=search)

    assert asked(replay, search=False) == asked(cfg, search=False)
    assert asked(cfg, search=True) != asked(cfg, search=False), "a session compares its search"
    assert config_drift(replay, run_dir, project_root=project) == ()
    resolved = tomllib.loads((run_dir / "config.resolved.toml").read_text(encoding="utf-8"))
    assert resolved[RUN_SEARCH_TABLE]["outputs"]["seepage_network"]["support"] == "network"


WINDOW = {"start": "2001-01-01", "end": "2003-12-31"}


def _doc(**calibration: object) -> dict:
    return make_document(
        "2000-01-01",
        "2005-12-31",
        step_unit="month",
        stream="n.gpkg",
        sections={"metrics": {"window": dict(WINDOW)}},
        **calibration,
    )


def test_sealed_metrics_window_reads_back() -> None:
    sealed = expand_calibration_protocol(_doc())

    again = expand_calibration_protocol(sealed)["calibration"]["phases"]

    assert again == sealed["calibration"]["phases"]


@pytest.mark.parametrize(
    ("declaration", "message"),
    [
        pytest.param({"version": "1"}, "needs a 'name'", id="table without a name"),
        pytest.param(5, "protocol name or a table carrying one, got int", id="not a table"),
    ],
)
def test_declaration_refusals(declaration, message) -> None:
    with pytest.raises(ValueError, match=message):
        expand_calibration_protocol({"calibration": {"protocol": declaration}})


def test_old_single_metric_spelling_declares_its_block_once() -> None:
    legacy = {"variable": "discharge", "objective": "rmse"}
    block = {"name": "b", "metric": "rmse"}
    produced = {"phases": [{"objective_blocks": ["b"]}] * 3, "objective_blocks": [block]}
    sealed = {"phases": ["kept as it is", legacy, legacy], "objective_blocks": []}

    read = registry._read_legacy_declaration(sealed, produced)

    assert read["objective_blocks"] == [block]
    assert read["phases"] == [
        "kept as it is",
        {"variable": None, "objective": None, "objective_blocks": ["b"]},
        {"variable": None, "objective": None, "objective_blocks": ["b"]},
    ]


@pytest.mark.parametrize(
    ("phase", "fresh"),
    [
        ({}, {"objective_blocks": ["b"]}),
        ({"objective": "rmse", "objective_blocks": ["b"]}, {"objective_blocks": ["b"]}),
        ({"objective": "rmse"}, {"objective_blocks": "b"}),
        ({"objective": "rmse"}, {"objective_blocks": ["b", "c"]}),
        ({"objective": "mae"}, {"objective_blocks": ["b"]}),
    ],
    ids=["no old spelling", "already a block", "not a list", "two blocks", "another metric"],
)
def test_old_spelling_needs_one_paired_block(phase, fresh) -> None:
    blocks = {"b": {"name": "b", "metric": "rmse"}}

    assert registry._fold_a_legacy_single_metric_stage(phase, fresh, blocks) == (None, None)


class _Incomparable:
    def __ne__(self, _other):
        raise TypeError("no order")


def test_incomparable_value_departs_from_the_paper() -> None:
    assert registry._departs(SimpleNamespace(paper_value=1.0), _Incomparable())
    assert not registry._departs(SimpleNamespace(paper_value=1.0), 1.0)


def test_network_outputs_read() -> None:
    first, second, gauge = (
        SimpleNamespace(support=kind) for kind in ("network", "network", "point")
    )
    outputs = {"a": first, "b": second, "g": gauge}

    named = SimpleNamespace(outputs=outputs, protocol=SimpleNamespace(network_output="b"))
    unnamed = SimpleNamespace(outputs=outputs, protocol=SimpleNamespace(network_output=None))

    assert registry._network_outputs_read(named) == [second]
    assert registry._network_outputs_read(unnamed) == [first, second]
    assert registry.deviations_in_force(SimpleNamespace(protocol=None)) == ()


def test_unknown_adjustable_key_is_not_moved(monkeypatch) -> None:
    real = registry.get_protocol("matching_hydrographic_network")
    stub = SimpleNamespace(name=real.name, adjustable=frozenset({"ghost", "storage"}))
    monkeypatch.setattr(registry, "get_protocol", lambda _name: stub)
    declared = MatchingHydrographicNetworkOptions(name=real.name, storage=False)

    assert registry.protocol_options_away_from_the_recipe(real.name, declared) == (
        {"key": "storage", "here": False, "recipe": "Sy"},
    )
