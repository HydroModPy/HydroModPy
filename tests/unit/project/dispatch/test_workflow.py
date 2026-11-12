"""Dispatch of a workflow name to its adapter (simulation, overview, calibration).

A plain run identical to a completed run gives that run back, found by its sealed
solution key in the manifests under runs/. A run is delivered to its destinations
whether it was computed or given back. A calibration delivers only the runs it promoted.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.project.facade as facade
from hydromodpy.core.exceptions import CalibrationError, ConfigError
from hydromodpy.core.state.scratch import active_run_scratch
from hydromodpy.project.dispatch import workflow as wf
from hydromodpy.project.request import RunOutcome, RunRequest
from hydromodpy.results.publication import PublishedLine


class _FakeRunner:
    """Stands for ``ProjectRunner``: records what ``run_simulation`` asks of it."""

    def __init__(self, project: _FakeProject) -> None:
        self.project = project

    def execute(self, request: RunRequest, **kwargs: Any) -> Any:
        self.project.executed.append(
            {"request": request, "scratch": active_run_scratch(), **kwargs}
        )
        return _FakeProject.result


class _FakeProject:
    """Stands for ``Project``: records what ``run_simulation`` asks of it."""

    instances: list[_FakeProject] = []
    result: Any = None

    def __init__(
        self,
        config: Any,
        *,
        base: Any = None,
        document: Any = None,
        source: Any = None,
        no_display: bool = False,
        environment: Any = None,
    ) -> None:
        self.args = {"base": base, "document": document, "source": source}
        self.no_display = no_display
        self.environment = environment
        self._cfg = config
        self._runner = _FakeRunner(self)
        self.executed: list[dict[str, Any]] = []
        _FakeProject.instances.append(self)

    def __enter__(self) -> _FakeProject:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _cfg(root: Path, name: str | None = "case", *, export: Any = ()) -> SimpleNamespace:
    return SimpleNamespace(
        simulation=SimpleNamespace(name=name),
        workspace=SimpleNamespace(project_root=str(root)),
        export=list(export),
    )


def _request(**members: Any) -> RunRequest:
    return RunRequest(config={}, **{"form": "dict", **members})


@pytest.fixture
def fake_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> type[_FakeProject]:
    """A ``Project`` double, a loader that gives ``_cfg(tmp_path)`` and an unchecked environment."""
    _FakeProject.instances = []
    _FakeProject.result = RunOutcome(
        name="case",
        run_dir=Path("/r/case"),
        sim_id="s" * 32,
        request_id="r" * 64,
        status="completed",
        identical_to=None,
        project_root=tmp_path,
    )
    monkeypatch.setattr(facade, "Project", _FakeProject)
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base)))
    monkeypatch.setattr(wf, "_checked_environment", lambda environment, root: environment)
    return _FakeProject


def test_unknown_workflow_refused(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="nonsense"):
        wf.dispatch_workflow("nonsense", _request(), base=tmp_path)


def test_dispatch_table() -> None:
    assert wf.DISPATCH == {
        "simulation": wf.run_simulation,
        "overview": wf.run_overview,
        "calibration": wf.run_calibration,
    }


@pytest.mark.parametrize("identical_to", [None, "case"], ids=["computed", "given back"])
def test_mesh_summary_of_a_built_run(
    fake_project: type[_FakeProject],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    identical_to: str | None,
) -> None:
    summary = {"engine": "gmsh", "product_key": "k1"}
    fake_project.result = RunOutcome(
        name="case",
        run_dir=tmp_path / "runs" / "case",
        sim_id="s" * 32,
        request_id="r" * 64,
        status="completed",
        identical_to=identical_to,
        project_root=tmp_path,
    )
    built = SimpleNamespace(
        setup=SimpleNamespace(mesh_summary=summary),
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(runs=[SimpleNamespace(process_type="mesh")])
        ),
    )
    monkeypatch.setattr(_FakeProject, "_ctx", built, raising=False)

    outcome = wf.run_simulation(_request(), base=tmp_path)

    assert outcome.mesh_summary == (None if identical_to else summary)


@pytest.mark.parametrize(
    "members",
    [{"resume": "r1"}, {"from_step": "extract"}, {"until_step": "run_solver"}],
    ids=["resume", "from_step", "until_step"],
)
def test_partial_run_skips_identical_lookup(
    members: dict[str, str], fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    wf.run_simulation(_request(**members), base=tmp_path)

    assert fake_project.instances[0].executed[0]["skip_identical"] is False


def test_unnamed_run_skips_identical_lookup(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base), name=None))

    wf.run_simulation(_request(), base=tmp_path)

    assert fake_project.instances[0].executed[0]["skip_identical"] is False


def test_bad_run_name_refused_first(fake_project: type[_FakeProject], tmp_path: Path) -> None:
    request = RunRequest.model_construct(
        config={}, name="Two Words", resume=None, set={}, overlays=(), form="dict"
    )
    with pytest.raises(ConfigError, match="two_words"):
        wf.run_simulation(request, base=tmp_path)
    assert fake_project.instances == []


def test_bare_resume_takes_config_name(fake_project: type[_FakeProject], tmp_path: Path) -> None:
    """The name comes from ``[simulation] name``, which a file folds from its stem."""
    wf.run_simulation(_request(resume=""), base=tmp_path)

    (project,) = fake_project.instances
    (executed,) = project.executed
    assert executed["request"].resume == "case"


def test_bare_resume_without_name_refused(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base), name=None))

    with pytest.raises(ConfigError, match="names none"):
        wf.run_simulation(_request(resume=""), base=tmp_path)
    assert fake_project.instances == []


def test_no_run_gives_none(fake_project: type[_FakeProject], tmp_path: Path) -> None:
    fake_project.result = None
    assert wf.run_simulation(_request(), base=tmp_path) is None


def test_replay_outcome_untouched(fake_project: type[_FakeProject], tmp_path: Path) -> None:
    fake_project.result = SimpleNamespace(
        name="case", sim_id="s", run_dir=Path("/r/case"), status="completed", identical_to="case"
    )

    outcome = wf.run_simulation(_request(), base=tmp_path, replay_of=tmp_path / "copy")

    assert outcome.identical_to == "case"
    assert fake_project.instances[0].executed[0]["replay_of"] == tmp_path / "copy"


def test_mesh_summary_needs_mesh_process() -> None:
    def project(process_types: list[str], summary: Any) -> SimpleNamespace:
        runs = [SimpleNamespace(process_type=p) for p in process_types]
        ctx = SimpleNamespace(
            setup=SimpleNamespace(mesh_summary=summary),
            execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=runs)),
        )
        return SimpleNamespace(_ctx=ctx)

    assert wf.mesh_summary_of(project(["mesh", "flow"], {"cells": 4})) == {"cells": 4}
    assert wf.mesh_summary_of(project(["flow"], {"cells": 4})) == {}
    assert wf.mesh_summary_of(project(["mesh"], "not a mapping")) == {}
    assert wf.mesh_summary_of(SimpleNamespace()) == {}


def _deliver_to_block() -> dict[str, Any]:
    return {"variables": "all", "deliver_to": ["ftp://example.org/incoming/"]}


def _preflight_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, Any, Any]]:
    """Record each preflight with the number of projects built before it."""
    from hydromodpy.project import deliver as deliver_module

    seen: list[tuple[int, Any, Any]] = []

    def probe(requests, environment, *, project_root):
        seen.append((len(_FakeProject.instances), requests, project_root))

    monkeypatch.setattr(deliver_module, "preflight", probe)
    return seen


def _deliver_run_spy(monkeypatch: pytest.MonkeyPatch, lines: tuple) -> list[dict[str, Any]]:
    """Record each delivery and give back *lines*."""
    from hydromodpy.project import deliver as deliver_module

    seen: list[dict[str, Any]] = []

    def deliver(run_dir, requests, environment, *, project_root):
        seen.append({"run_dir": run_dir, "requests": requests, "project_root": project_root})
        return lines

    monkeypatch.setattr(deliver_module, "deliver_run", deliver)
    return seen


def _published_line() -> PublishedLine:
    return PublishedLine(
        kind="delivery",
        published_at=datetime(2026, 11, 10, tzinfo=UTC),
        file="exports/head_last.tif",
        destination="ftp://example.org/incoming/head_last.tif",
        state="delivered",
        sha256=hashlib.sha256(b"head").hexdigest(),
        bytes=4,
        attempts=1,
    )


def test_deliver_to_checked_before_claim(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocks = [_deliver_to_block()]
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base), export=blocks))
    seen = _preflight_spy(monkeypatch)
    _deliver_run_spy(monkeypatch, ())

    wf.run_simulation(_request(), base=tmp_path)

    assert seen == [(0, blocks, tmp_path.resolve())]
    assert fake_project.instances[0].executed


def test_replay_checks_no_destination(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        wf, "_loaded", lambda request, base: _cfg(Path(base), export=[_deliver_to_block()])
    )
    seen = _preflight_spy(monkeypatch)

    wf.run_simulation(_request(), base=tmp_path, replay_of=tmp_path / "copy")

    assert seen == []


@pytest.mark.parametrize("identical_to", [None, "case"], ids=["computed", "given back"])
def test_run_delivered_keeps_status(
    fake_project: type[_FakeProject],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    identical_to: str | None,
) -> None:
    # deliver_to is not part of the request id, so a run given back is delivered too.
    line = _published_line()
    blocks = [_deliver_to_block()]
    fake_project.result = RunOutcome(
        name="case",
        run_dir=tmp_path / "runs" / "case",
        sim_id="s" * 32,
        request_id="r" * 64,
        status="completed",
        identical_to=identical_to,
        project_root=tmp_path,
    )
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base), export=blocks))
    _preflight_spy(monkeypatch)
    delivered = _deliver_run_spy(monkeypatch, (line,))

    outcome = wf.run_simulation(_request(), base=tmp_path)

    assert outcome.deliveries == (line,)
    assert (outcome.status, outcome.identical_to) == ("completed", identical_to)
    assert delivered == [
        {"run_dir": tmp_path / "runs" / "case", "requests": blocks, "project_root": tmp_path}
    ]


def test_identical_run_needs_a_key(tmp_path: Path) -> None:
    (tmp_path / "runs" / "case").mkdir(parents=True)
    assert wf.completed_identical_run(tmp_path, "case", None) is None


def test_run_view_indexes_then_reads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hydromodpy.project.runner as runner
    import hydromodpy.results.catalog.indexer as indexer

    order: list[Any] = []
    monkeypatch.setattr(indexer, "index_after_run", lambda root: order.append(("index", root)))
    monkeypatch.setattr(
        runner,
        "run_view_of",
        lambda run_dir, *, project_root, sim_id: order.append(("view", run_dir, sim_id)) or "V",
    )
    outcome = SimpleNamespace(
        project_root=tmp_path, run_dir=tmp_path / "runs" / "case", sim_id="sid"
    )
    assert wf.completed_run_view(outcome) == "V"
    assert order[0] == ("index", tmp_path)
    assert order[1][0] == "view"
    assert order[1][1].name == "case"
    assert order[1][2] == "sid"


def _phases_loader(monkeypatch: pytest.MonkeyPatch, names: list[str] | Exception) -> None:
    import hydromodpy.calibration.runners.document as document

    def load(path: Path) -> tuple[Any, dict]:
        if isinstance(names, Exception):
            raise names
        return SimpleNamespace(phases=[SimpleNamespace(name=n) for n in names]), {}

    monkeypatch.setattr(document, "load_toml_calibration", load)


_CALIBRATION = """\
[simulation]
name = "case"

[calibration]
method = "sceua"

[[calibration.parameters]]
name = "sy"
"""

_CALIBRATION_WITH_DELIVERY = (
    _CALIBRATION
    + """
[[export]]
variables = "all"
deliver_to = "ftp://example.org/incoming/"
"""
)


@pytest.fixture
def calibration_runners(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    import hydromodpy.calibration.preflight as preflight
    import hydromodpy.calibration.runners.cli_runner as cli
    import hydromodpy.calibration.runners.staged_runner as staged

    # The file of the requests exists and declares no [[export]] block.
    (tmp_path / "c.toml").write_text(_CALIBRATION, encoding="utf-8")
    called: list[str] = []
    monkeypatch.setattr(preflight, "preflight_launch", lambda target: called.append("preflight"))
    monkeypatch.setattr(
        staged,
        "run_staged_calibration",
        lambda target, *, phase, bounds, **kw: (
            called.append(f"staged:{phase}") or SimpleNamespace(to_dict=lambda: {"kind": "staged"})
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_calibration_cli",
        lambda target, *, bounds, **kw: (
            called.append("flat") or SimpleNamespace(to_dict=lambda: {"kind": "flat"})
        ),
    )
    monkeypatch.setattr(
        wf, "_checked_environment", lambda environment, root: SimpleNamespace(bounds=None)
    )
    monkeypatch.setattr(wf, "_completed_session", lambda target: None)
    return called


def _file_request(**members: Any) -> RunRequest:
    return RunRequest(config={}, form="toml", source="c.toml", **members)


ROUTES = [
    pytest.param(["warm"], {"phase": "warm"}, "staged", ["preflight", "staged:warm"], id="phased"),
    pytest.param([], {}, "flat", ["preflight", "flat"], id="flat"),
]


@pytest.mark.parametrize(("phases", "members", "kind", "calls"), ROUTES)
def test_calibration_routing(
    phases, members, kind, calls, monkeypatch, calibration_runners, tmp_path
) -> None:
    _phases_loader(monkeypatch, phases)

    result = wf.run_calibration(_file_request(**members), base=tmp_path)

    assert result == {"kind": kind}
    assert calibration_runners == calls


def test_undeclared_phase_refused(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    _phases_loader(monkeypatch, [])
    with pytest.raises(CalibrationError, match="no phase 'warm'"):
        wf.run_calibration(_file_request(phase="warm"), base=tmp_path)


def test_completed_session_given_back(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    _phases_loader(monkeypatch, [])
    answer = {"skipped": True, "name": "c", "sim_id": "sid"}
    monkeypatch.setattr(wf, "_completed_session", lambda target: answer)

    assert wf.run_calibration(_file_request(), base=tmp_path) == answer
    assert calibration_runners == ["preflight"]


@pytest.mark.parametrize(
    "members",
    [{"force": True}, {"resume": ""}, {"phase": "warm"}],
    ids=["force", "resume", "one-phase"],
)
def test_calibration_searches_again(
    members: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    calibration_runners: list[str],
    tmp_path: Path,
) -> None:
    _phases_loader(monkeypatch, ["warm"])
    monkeypatch.setattr(wf, "_completed_session", lambda target: {"skipped": True})

    result = wf.run_calibration(_file_request(**members), base=tmp_path)

    assert result == {"kind": "staged"}


def test_held_calibration_forwards_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:

    asked: dict[str, Any] = {}

    class _Project:
        def __init__(self, cfg, **kwargs) -> None:
            asked["source"] = kwargs["source"]

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def calibrate(self, **options):
            asked["options"] = options
            return SimpleNamespace(to_dict=lambda: {"kind": "memory"})

    monkeypatch.setattr(
        wf,
        "_loaded",
        lambda request, base: SimpleNamespace(
            workspace=SimpleNamespace(project_root=str(base)), export=[]
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.project.run_overrides.override_changes", lambda cfg, changes: {}
    )
    monkeypatch.setattr(facade, "Project", _Project)
    request = _file_request(name="other", force=True)

    assert wf._calibrate_in_memory(request, tmp_path, None) == {"kind": "memory"}
    assert asked["source"] is None, "a case the request names runs without its file"
    assert asked["options"] == {
        "phase": None,
        "resume": False,
        "workspace": tmp_path,
        "force": True,
        "case": "other",
    }


@pytest.mark.parametrize(
    ("summary", "delivered"),
    [
        ({"status": "completed", "best_rel_dir": "sessions/case/best"}, ["sessions/case/best"]),
        ({"status": "completed", "best_rel_dir": None}, []),
        (
            {
                "status": "completed",
                "best_cases": {
                    "north": {"rel_dir": "sessions/north/best"},
                    "south": {"rel_dir": "sessions/south/best"},
                },
            },
            ["sessions/north/best", "sessions/south/best"],
        ),
        ({"status": "partial", "best_rel_dir": "sessions/case/best"}, []),
    ],
    ids=["promoted", "no-best", "each-case", "partial"],
)
def test_calibration_delivers_promoted_runs(
    summary: dict[str, Any],
    delivered: list[str],
    monkeypatch: pytest.MonkeyPatch,
    calibration_runners: list[str],
    tmp_path: Path,
) -> None:
    """The trials stay where they ran: only ``best_rel_dir`` reaches the destination."""
    _phases_loader(monkeypatch, [])
    (tmp_path / "c.toml").write_text(_CALIBRATION_WITH_DELIVERY, encoding="utf-8")
    import hydromodpy.calibration.runners.cli_runner as cli

    report = {"kind": "flat", "workspace": str(tmp_path), **summary}
    monkeypatch.setattr(
        cli,
        "run_calibration_cli",
        lambda target, *, bounds, **kw: SimpleNamespace(to_dict=lambda: report),
    )
    from hydromodpy.project import deliver as deliver_module

    probed: list[Path] = []
    monkeypatch.setattr(
        deliver_module,
        "preflight",
        lambda requests, environment, *, project_root: probed.append(project_root),
    )
    line = _published_line()
    seen = _deliver_run_spy(monkeypatch, (line,))

    result = wf.run_calibration(_file_request(), base=tmp_path)

    assert probed == [tmp_path.resolve()]

    assert seen == [
        {
            "run_dir": tmp_path / rel_dir,
            "requests": wf._export_requests_of(tmp_path / "c.toml"),
            "project_root": tmp_path.resolve(),
        }
        for rel_dir in delivered
    ]
    assert result["deliveries"] == [line.model_dump(mode="json", exclude_none=True)] * len(
        delivered
    )


def test_held_calibration_delivers_best(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:

    (tmp_path / "c.toml").write_text(_CALIBRATION_WITH_DELIVERY, encoding="utf-8")
    blocks = wf._export_requests_of(tmp_path / "c.toml")
    cfg = SimpleNamespace(workspace=SimpleNamespace(project_root=str(tmp_path)), export=blocks)

    class _Project:
        def __init__(self, cfg, **kwargs) -> None:
            self.cfg = cfg

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def calibrate(self, **options):
            return SimpleNamespace(
                to_dict=lambda: {"status": "completed", "best_rel_dir": "sessions/case/best"}
            )

    monkeypatch.setattr(wf, "_loaded", lambda request, base: cfg)
    monkeypatch.setattr(
        "hydromodpy.project.run_overrides.override_changes", lambda cfg, changes: {}
    )
    monkeypatch.setattr(facade, "Project", _Project)
    from hydromodpy.project import deliver as deliver_module

    probed: list[Path] = []
    monkeypatch.setattr(
        deliver_module,
        "preflight",
        lambda requests, environment, *, project_root: probed.append(project_root),
    )
    line = _published_line()
    seen = _deliver_run_spy(monkeypatch, (line,))

    result = wf._calibrate_in_memory(_file_request(name="other"), tmp_path, None)

    assert probed == [tmp_path]
    assert seen == [
        {
            "run_dir": tmp_path / "sessions" / "case" / "best",
            "requests": blocks,
            "project_root": tmp_path,
        }
    ]
    assert result == {
        "status": "completed",
        "best_rel_dir": "sessions/case/best",
        "deliveries": [line.model_dump(mode="json", exclude_none=True)],
    }


_PHASED_CALIBRATION = """\
[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[geographic]
source_mode = "synthetic"

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[calibration]
method = "grid"
max_trials = 4
method_options = { points_per_dim = 4 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"

[[calibration.phases]]
name = "warm"
parameters = ["K"]
"""


@pytest.fixture
def staged_session(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The staged runner a held calibration reaches, recording the document it is handed."""
    import hydromodpy.calibration.preflight as preflight
    import hydromodpy.calibration.runners.staged_runner as staged

    seen: dict[str, Any] = {}

    def run_staged(document: Path, **options: Any) -> SimpleNamespace:
        seen["document"] = Path(document)
        seen["options"] = options
        return SimpleNamespace(to_dict=lambda: {"kind": "staged"})

    monkeypatch.setattr(preflight, "preflight_launch", lambda *args, **kwargs: None)
    monkeypatch.setattr(staged, "run_staged_calibration", run_staged)
    return seen


def test_phased_file_freezes_set_changes(tmp_path: Path, staged_session: dict[str, Any]) -> None:
    """The session freezes the value of ``--set``, under the case of the file, in its project."""
    import tomllib

    from hydromodpy.project.request import request_of

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    source = tmp_path / "Calib File.toml"
    source.write_text(_PHASED_CALIBRATION, encoding="utf-8")
    request = request_of(source, base=tmp_path, set={"flow.param.K.field.value": 3e-5})

    assert wf.run_calibration(request, base=tmp_path) == {"kind": "staged"}

    document = staged_session["document"]
    frozen = tomllib.loads(document.read_text(encoding="utf-8"))
    assert frozen["flow"]["param"]["K"]["field"]["value"] == 3e-5
    assert document == tmp_path.resolve() / "sessions" / "calib_file.toml"


def test_json_request_runs_its_document(tmp_path: Path, staged_session: dict[str, Any]) -> None:
    import json
    import tomllib

    from hydromodpy.project.request import REQUEST_SCHEMA, request_of

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    source = tmp_path / "calib.json"
    document = tomllib.loads(_PHASED_CALIBRATION)
    source.write_text(json.dumps({"schema": REQUEST_SCHEMA, "config": document}), "utf-8")
    request = request_of(source, base=tmp_path)

    assert wf.run_calibration(request, base=tmp_path) == {"kind": "staged"}
    assert staged_session["document"].parent == tmp_path.resolve() / "sessions"


def _draft_collaborators(monkeypatch: pytest.MonkeyPatch, *, is_sites: bool) -> list[Any]:
    import hydromodpy.config.sites as sites
    import hydromodpy.project.launch.plan as expansion
    import hydromodpy.workflow.dispatch as wdispatch

    seen: list[Any] = []
    monkeypatch.setattr(wdispatch, "load_raw_toml", lambda path: {"raw": str(path)})
    monkeypatch.setattr(sites, "is_sites_project", lambda raw: is_sites)
    monkeypatch.setattr(
        expansion,
        "expand_plan",
        lambda root, path, *, set_overrides: seen.append(("plan", path, set_overrides)) or "PLAN",
    )
    monkeypatch.setattr(
        expansion,
        "single_case_draft",
        lambda cfg, **kw: seen.append(("single", cfg, kw)) or "ONE",
    )
    return seen


def test_sites_file_drafts_its_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen = _draft_collaborators(monkeypatch, is_sites=True)
    path = tmp_path / "sites.toml"
    draft = wf.draft_of_a_file_or_config(
        path, workflow="simulation", set_changes={"flow.recharge": 2}
    )
    assert draft == "PLAN"
    assert seen == [("plan", path, {"flow": {"recharge": 2}})]


def test_overview_drafts_one_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hydromodpy.display.overview.location as display_overview

    seen = _draft_collaborators(monkeypatch, is_sites=False)
    monkeypatch.setattr(display_overview, "overview_name", lambda site, name: f"{site}/{name}")
    cfg = SimpleNamespace(site=SimpleNamespace(name="alpha"), overview=SimpleNamespace(name="ov"))
    assert wf.draft_of_a_file_or_config(cfg, workflow="overview") == "ONE"
    _kind, got_cfg, kwargs = seen[0]
    assert got_cfg is cfg
    assert kwargs == {
        "name": "alpha/ov",
        "config_path": None,
        "steps": (),
        "kind": "overview",
    }


def test_overview_launcher_gets_bounds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hydromodpy.core.runtime.bounds import Bounds
    from hydromodpy.project.environment import Environment
    from hydromodpy.workflow import overview as overview_module

    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, cfg: Any, *, base: Any, source: Any = None, bounds: Any = None) -> None:
            seen.update(cfg=cfg, base=base, source=source, bounds=bounds)
            raise ConfigError("captured")

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(overview_module, "DataOverviewLauncher", _Spy)
    monkeypatch.setattr(wf, "_loaded", lambda request, base: cfg)
    monkeypatch.setattr(wf, "_checked_environment", lambda environment, root: environment)
    environment = Environment(bounds=Bounds(allowed_hosts=frozenset({"data.geopf.fr"})))

    with pytest.raises(ConfigError):
        wf.run_overview(
            _request(source="overview.toml", form="toml"), base=tmp_path, environment=environment
        )

    assert seen["cfg"] is cfg
    assert seen["base"] == tmp_path.resolve()
    assert seen["source"] == tmp_path.resolve() / "overview.toml"
    assert seen["bounds"] == environment.bounds


_OVERVIEW = """\
[site]
name = "nancon"

[workflow]
mode = "overview"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[overview]
name = "identity card"
"""


def test_overview_applies_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hydromodpy.project.request import request_of
    from hydromodpy.workflow import overview as overview_module

    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, cfg: Any, **kwargs: Any) -> None:
            seen["name"] = cfg.overview.name
            raise ConfigError("captured")

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    source = tmp_path / "overview.toml"
    source.write_text(_OVERVIEW, encoding="utf-8")
    monkeypatch.setattr(overview_module, "DataOverviewLauncher", _Spy)
    request = request_of(source, base=tmp_path, set={"overview.name": "winter card"})

    with pytest.raises(ConfigError, match="captured"):
        wf.run_overview(request, base=tmp_path)

    assert seen["name"] == "winter card"


def test_simulation_drafts_by_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _draft_collaborators(monkeypatch, is_sites=False)
    seen: dict[str, Any] = {}

    class _Dry(_FakeProject):
        def simulate(self, **kwargs: Any) -> str:
            seen.update(kwargs)
            return "DRY"

    monkeypatch.setattr(facade, "Project", _Dry)
    cfg = SimpleNamespace()
    draft = wf.draft_of_a_file_or_config(
        cfg, workflow="simulation", set_changes={"a": 1}, name="n", from_step="extract"
    )
    assert _Dry.instances[-1].args["base"] is None
    assert draft == "DRY"
    assert seen == {
        "dry_run": True,
        "set": {"a": 1},
        "name": "n",
        "resume": None,
        "from_step": "extract",
        "until_step": None,
    }


def test_newest_sealed_version_answers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hydromodpy.results.retention as retention
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    runs = tmp_path / "runs"
    for name in ("case", "case.v2", "case.v3", "other"):
        (runs / name).mkdir(parents=True)
    (runs / "stray.txt").write_text("x", encoding="utf-8")
    sealed = {"case": "H", "case.v2": "H", "case.v3": "unsealed-or-other", "other": "H"}
    monkeypatch.setattr(sealing, "sealed_solution_key", lambda run_dir: sealed[run_dir.name])
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda run_dir, root: True)
    monkeypatch.setattr(retention, "level_at", lambda run_dir: "result")

    assert wf.completed_identical_run(tmp_path, "case", "H") == runs / "case.v2"
    sealed["case.v2"] = sealed["case"] = "different"
    assert wf.completed_identical_run(tmp_path, "case", "H") is None
    assert wf.completed_identical_run(tmp_path, "case", None) is None


def test_research_version_does_not_answer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An identical trial keeps its level: only a run of ``result`` or above answers."""
    import hydromodpy.results.retention as retention
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    runs = tmp_path / "runs"
    for name in ("case", "case.v2"):
        (runs / name).mkdir(parents=True)
    monkeypatch.setattr(sealing, "sealed_solution_key", lambda run_dir: "H")
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda run_dir, root: True)
    levels = {"case": "research", "case.v2": "result"}
    monkeypatch.setattr(retention, "level_at", lambda run_dir: levels[run_dir.name])

    assert wf.completed_identical_run(tmp_path, "case", "H") == runs / "case.v2"

    levels.update({"case": "research", "case.v2": "research"})
    assert wf.completed_identical_run(tmp_path, "case", "H") is None


def test_vanished_api_file_blocks_give_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The request holds the declaration of such a file, so the guard reads its bytes."""
    import hydromodpy.results.retention as retention
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    (tmp_path / "runs" / "case").mkdir(parents=True)
    monkeypatch.setattr(sealing, "sealed_solution_key", lambda run_dir: "K")
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda run_dir, root: False)
    monkeypatch.setattr(retention, "level_at", lambda run_dir: "result")

    assert wf.completed_identical_run(tmp_path, "case", "K") is None


def _run_that_read(tmp_path: Path, *entries: dict[str, Any]) -> Path:
    """A run directory whose ``inputs.json`` lists *entries*, under a project with no workspace."""
    from hydromodpy.results.record.manifest import InputEntry
    from hydromodpy.results.record.record import InputsDocument

    run_dir = tmp_path / "runs" / "demo"
    run_dir.mkdir(parents=True)
    document = InputsDocument(sim_id="s", inputs=[InputEntry(**entry) for entry in entries])
    (run_dir / "inputs.json").write_text(document.model_dump_json(by_alias=True), encoding="utf-8")
    return run_dir


def _digest(path: Path) -> str:
    from hydromodpy.core.io.file_digest import sha256_of

    return sha256_of(path)


@pytest.mark.parametrize(
    ("change", "intact"),
    [
        ("none", True),
        ("edited", False),
        ("deleted", False),
        ("user-file-edited", True),
        ("no-inputs-file", False),
        ("a-folder", True),
    ],
)
def test_api_inputs_intact(tmp_path: Path, change: str, intact: bool) -> None:
    from hydromodpy.workflow.replay_checks import api_inputs_intact

    api = tmp_path / "data" / "climate" / "safran.nc"
    own = tmp_path / "inputs" / "k.csv"
    api.parent.mkdir(parents=True)
    own.parent.mkdir(parents=True)
    api.write_bytes(b"as the provider gave it")
    own.write_text("1", encoding="utf-8")
    entries = [
        {
            "variable": "climate",
            "provider": "safran",
            "path": "data/climate/safran.nc",
            "sha256": _digest(api),
        },
        {"variable": "k", "provider": "file", "path": "inputs/k.csv", "sha256": _digest(own)},
    ]
    if change == "a-folder":
        (tmp_path / "data" / "folder").mkdir()
        entries.append(
            {"variable": "x", "provider": "safran", "path": "data/folder", "sha256": "z"}
        )
    run_dir = _run_that_read(tmp_path, *entries)
    if change == "edited":
        api.write_bytes(b"refreshed by the provider")
    elif change == "deleted":
        api.unlink()
    elif change == "user-file-edited":
        own.write_text("2", encoding="utf-8")
    elif change == "no-inputs-file":
        (run_dir / "inputs.json").unlink()

    assert api_inputs_intact(run_dir, tmp_path) is intact
