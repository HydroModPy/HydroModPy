"""Tests of `protocols.registry`."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import MatchingHydrographicNetworkOptions, apply_project_defaults
from hydromodpy.calibration.protocols import expand_calibration_protocol, registry
from hydromodpy.calibration.protocols.registry import _as_the_load_reads_it
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.results.catalog.registration import config_identity_hash, solve_identity_hash
from hydromodpy.results.storage.contract import RUN_SEARCH_TABLE
from hydromodpy.workflow.steps.prepare_solver.freeze import (
    frozen_config_of,
    portable_config_document,
    search_of,
)
from hydromodpy.workflow.steps.prepare_solver.resolved import config_drift, resolved_config_document
from tests.unit.calibration._factories_scoring import make_document

# From test_a_frozen_protocol_config_reads_back.py
# A run calibrated by a protocol replays from its own frozen ``config.toml``.
#
# The frozen document carries the ``protocol`` table and the stages it wrote,
# and the load compares the two. It used to compare them before the load
# writes ``[site] gauge`` into each stage and ``[metrics] window`` into a
# transient stage without one, so the stages the run itself had frozen read
# as a contradiction of its protocol, and ``hmp catalog rerun`` or
# ``hmp run --resume`` refused the run.


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


def _phases(cfg: HydroModPyConfig) -> list[dict]:
    return [phase.model_dump(mode="json") for phase in cfg.calibration.phases]


def test_the_stages_carry_no_station_and_read_back(tmp_path: Path) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    frozen = _frozen(project)
    stages = tomllib.loads(frozen.read_text(encoding="utf-8"))["calibration"]["phases"]
    assert ["observed_station_id" in stage for stage in stages] == [False, False]

    replayed = HydroModPyConfig.from_toml(frozen)

    assert _phases(replayed) == _phases(HydroModPyConfig.from_toml(project / "project.toml"))


def test_the_metrics_window_written_into_the_transient_stage_reads_back(
    tmp_path: Path,
) -> None:
    """A run of one year leaves nothing past the spin-up: ``[metrics] window`` windows it."""
    project = _project(tmp_path, start="2000-01-01", end="2000-12-31")
    frozen = _frozen(project)
    stages = tomllib.loads(frozen.read_text(encoding="utf-8"))["calibration"]["phases"]
    assert stages[1]["window"]["start"] == "2000-01-01"

    replayed = HydroModPyConfig.from_toml(frozen)

    assert _phases(replayed) == _phases(HydroModPyConfig.from_toml(project / "project.toml"))


def test_a_stage_that_names_another_window_is_still_refused(tmp_path: Path) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    frozen = _frozen(project)
    document = tomllib.loads(frozen.read_text(encoding="utf-8"))
    document["calibration"]["phases"][1]["window"] = {"start": "2002-01-01"}

    with pytest.raises(ConfigValidationError, match="phases"):
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})


def test_a_station_sealed_in_a_stage_is_dropped_on_read(tmp_path: Path) -> None:
    project = _project(tmp_path, start="2000-01-01", end="2002-12-31")
    document = tomllib.loads(_frozen(project).read_text(encoding="utf-8"))
    document["calibration"]["phases"][0]["observed_station_id"] = "OTHER"

    replayed = HydroModPyConfig.from_snapshot(
        {**document, "workspace": {"project_root": str(project)}}
    )

    assert _phases(replayed) == _phases(HydroModPyConfig.from_toml(project / "project.toml"))


def test_a_run_of_a_calibration_seals_its_own_solve(tmp_path: Path) -> None:
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
    assert solve_identity_hash(replay) == solve_identity_hash(cfg)
    assert config_identity_hash(cfg) != solve_identity_hash(cfg), "a session compares its search"
    assert config_drift(replay, run_dir, project_root=project) == ()
    resolved = tomllib.loads((run_dir / "config.resolved.toml").read_text(encoding="utf-8"))
    assert resolved[RUN_SEARCH_TABLE]["outputs"]["seepage_network"]["support"] == "network"


# From test_the_metrics_window_reaches_the_protocol_s_transient_stage.py
# Under a protocol, ``[metrics] window`` is the window of the transient stage.
#
# The run is scored on ``[metrics] window`` and a calibration takes it by default
# on every phase that writes no window (H45). The protocol used to write its own
# default, one year past the start with no end, before the project defaults ran,
# so the stage already carried a window and kept it: the end of ``[metrics]
# window`` was lost and the session scored past it. The spin-up default now
# applies only without ``[metrics] window``.


NAME = "matching_hydrographic_network"
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


def _loaded_stages(doc: dict) -> list[dict]:
    """Return the stages as the load writes them: expansion, then project defaults."""
    raw = expand_calibration_protocol(copy.deepcopy(doc))
    calibration = apply_project_defaults(
        raw["calibration"], site_gauge=None, metrics_window=raw["metrics"]["window"]
    )
    return calibration["phases"]


def test_the_transient_stage_scores_the_metrics_window_with_both_bounds() -> None:
    steady, transient = _loaded_stages(_doc())

    assert transient["window"] == WINDOW
    assert "window" not in steady


def test_the_transient_stage_scores_the_metrics_window_less_the_validation() -> None:
    early = {"start": "2001-01-01", "end": "2002-12-31"}
    doc = _doc(validation_window={"start": "2003-01-01", "end": "2003-12-31"})

    calibration = expand_calibration_protocol(copy.deepcopy(doc))["calibration"]

    assert calibration["phases"][1]["window"] == early
    assert _as_the_load_reads_it("phases", calibration, doc)[1]["window"] == early


def test_the_expansion_itself_writes_the_window() -> None:
    _, transient = expand_calibration_protocol(_doc())["calibration"]["phases"]

    assert transient["window"] == WINDOW
    assert "spin-up" not in transient["description"]
    assert "2003-12-31" in transient["description"]


def test_without_a_metrics_window_the_spin_up_default_stays() -> None:
    doc = _doc()
    del doc["metrics"]

    _, transient = expand_calibration_protocol(doc)["calibration"]["phases"]

    assert transient["window"] == {"start": "2001-01-01"}


def test_a_window_on_the_protocol_still_wins() -> None:
    doc = _doc(protocol={"name": NAME, "window": {"start": "2002-01-01"}})

    _, transient = _loaded_stages(doc)

    assert transient["window"] == {"start": "2002-01-01", "end": "2003-12-31"}


def test_a_stage_sealed_with_the_spin_up_window_replays_it() -> None:
    """A run sealed before this fix carries the spin-up window and reads back with it."""
    doc = _doc()
    del doc["metrics"]
    sealed = {**expand_calibration_protocol(doc), "metrics": {"window": dict(WINDOW)}}

    _, transient = expand_calibration_protocol(sealed)["calibration"]["phases"]

    assert transient["window"] == {"start": "2001-01-01"}


def test_a_stage_sealed_with_the_metrics_window_reads_back() -> None:
    sealed = expand_calibration_protocol(_doc())

    again = expand_calibration_protocol(sealed)["calibration"]["phases"]

    assert again == sealed["calibration"]["phases"]


# The readers of a declaration, on the shapes a file or a plugin can bring.


@pytest.mark.parametrize(
    ("declaration", "message"),
    [({"version": "1"}, "needs a 'name'"), (5, "protocol name or a table carrying one, got int")],
)
def test_a_declaration_with_no_name_or_no_table_is_refused(declaration, message) -> None:
    with pytest.raises(ValueError, match=message):
        expand_calibration_protocol({"calibration": {"protocol": declaration}})


def test_a_stage_sealed_with_the_old_single_metric_spelling_declares_its_block_once() -> None:
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
    ids=["no_old_spelling", "already_a_block", "not_a_list", "two_blocks", "another_metric"],
)
def test_a_stage_is_not_read_as_the_old_spelling_unless_it_pairs_with_one_block(
    phase, fresh
) -> None:
    blocks = {"b": {"name": "b", "metric": "rmse"}}

    assert registry._fold_a_legacy_single_metric_stage(phase, fresh, blocks) == (None, None)


class _Incomparable:
    def __ne__(self, _other):
        raise TypeError("no order")


def test_a_value_that_cannot_be_compared_to_the_publication_departs_from_it() -> None:
    assert registry._departs(SimpleNamespace(paper_value=1.0), _Incomparable())
    assert not registry._departs(SimpleNamespace(paper_value=1.0), 1.0)


def test_the_network_read_is_the_one_named_else_every_network_output() -> None:
    first, second, gauge = (
        SimpleNamespace(support=kind) for kind in ("network", "network", "point")
    )
    outputs = {"a": first, "b": second, "g": gauge}

    named = SimpleNamespace(outputs=outputs, protocol=SimpleNamespace(network_output="b"))
    unnamed = SimpleNamespace(outputs=outputs, protocol=SimpleNamespace(network_output=None))

    assert registry._network_outputs_read(named) == [second]
    assert registry._network_outputs_read(unnamed) == [first, second]
    assert registry.deviations_in_force(SimpleNamespace(protocol=None)) == ()


def test_an_adjustable_key_the_options_do_not_carry_is_never_reported_as_moved(monkeypatch) -> None:
    real = registry.get_protocol("matching_hydrographic_network")
    stub = SimpleNamespace(name=real.name, adjustable=frozenset({"ghost", "storage"}))
    monkeypatch.setattr(registry, "get_protocol", lambda _name: stub)
    declared = MatchingHydrographicNetworkOptions(name=real.name, storage=False)

    assert registry.protocol_options_away_from_the_recipe(real.name, declared) == (
        {"key": "storage", "here": False, "recipe": "Sy"},
    )
