"""The workflow dispatch routes a workflow name to its adapter and skips sealed identical runs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.project as project_pkg
from hydromodpy.core.exceptions import CalibrationError, ConfigError
from hydromodpy.project.dispatch import workflow as wf


class _FakeProject:
    """Stands for ``Project``: records what ``run_simulation`` asks of it."""

    instances: list[_FakeProject] = []
    result: Any = None
    cfg_of_a_file: Any = None

    def __init__(self, config: Any, *, no_display: bool = False, headless: bool = False) -> None:
        self.args = (config, no_display, headless)
        self._cfg = config if not isinstance(config, (str, Path)) else _FakeProject.cfg_of_a_file
        self._ctx = None
        self.executed: list[dict[str, Any]] = []
        _FakeProject.instances.append(self)

    def __enter__(self) -> _FakeProject:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _execute(self, **kwargs: Any) -> Any:
        self.executed.append(kwargs)
        return _FakeProject.result


def _cfg(root: Path, name: str | None = "case") -> SimpleNamespace:
    return SimpleNamespace(
        simulation=SimpleNamespace(name=name),
        workspace=SimpleNamespace(project_root=str(root)),
        with_changes=lambda changes: SimpleNamespace(
            simulation=SimpleNamespace(name=name),
            workspace=SimpleNamespace(project_root=str(root)),
            changed=dict(changes),
        ),
    )


@pytest.fixture
def fake_project(monkeypatch: pytest.MonkeyPatch) -> type[_FakeProject]:
    _FakeProject.instances = []
    _FakeProject.result = SimpleNamespace(
        name="case", sim_id="s" * 32, run_dir="/r/case", status="completed"
    )
    monkeypatch.setattr(project_pkg, "Project", _FakeProject)
    return _FakeProject


@pytest.mark.parametrize("workflow", ["simulation", "overview", "calibration"])
def test_dispatch_workflow_routes_by_workflow_name(
    workflow: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Path, dict[str, Any]]] = []
    for key in wf.DISPATCH:
        monkeypatch.setitem(
            wf.DISPATCH, key, lambda path, _key=key, **kw: calls.append((_key, path, kw)) or _key
        )
    assert wf.dispatch_workflow(workflow, Path("a.toml"), force=True) == workflow
    assert calls == [(workflow, Path("a.toml"), {"force": True})]


def test_dispatch_workflow_refuses_an_unknown_workflow() -> None:
    with pytest.raises(KeyError, match="nonsense"):
        wf.dispatch_workflow("nonsense", Path("a.toml"))


def test_the_dispatch_table_names_the_three_adapters() -> None:
    assert wf.DISPATCH == {
        "simulation": wf.run_simulation,
        "overview": wf.run_overview,
        "calibration": wf.run_calibration,
    }


def test_run_simulation_skips_a_run_identical_to_a_sealed_one(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "completed_identical_run", lambda cfg, *, name: ("case.v2", "sid-1"))
    summary = wf.run_simulation(_cfg(tmp_path))
    assert summary == {
        "skipped": True,
        "name": "case.v2",
        "sim_id": "sid-1",
        "project_root": str(tmp_path),
    }
    assert fake_project.instances[0].executed == []


def test_run_simulation_force_runs_despite_an_identical_sealed_run(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "completed_identical_run", lambda cfg, *, name: ("case", "sid-1"))
    summary = wf.run_simulation(_cfg(tmp_path), force=True)
    assert "skipped" not in summary
    assert summary["sim_id"] == "s" * 32
    assert fake_project.instances[0].executed[0]["force"] is True


@pytest.mark.parametrize(
    "kwargs",
    [{"resume": "r1"}, {"from_step": "extract"}, {"until_step": "run_solver"}],
    ids=["resume", "from_step", "until_step"],
)
def test_run_simulation_partial_runs_never_look_for_an_identical_run(
    kwargs: dict[str, str],
    fake_project: type[_FakeProject],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def explode(cfg: Any, *, name: str) -> None:
        raise AssertionError("must not be asked")

    monkeypatch.setattr(wf, "completed_identical_run", explode)
    wf.run_simulation(_cfg(tmp_path), **kwargs)
    assert fake_project.instances[0].executed


def test_run_simulation_runs_when_no_identical_run_is_sealed(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.project.run_overrides as ro

    monkeypatch.setattr(ro, "override_changes", lambda cfg, ch: {})
    monkeypatch.setattr(wf, "completed_identical_run", lambda cfg, *, name: None)
    summary = wf.run_simulation(
        _cfg(tmp_path), changes={"a": 1}, overrides={"flow.x": 2}, name="mine", fresh=True
    )
    sent = fake_project.instances[0].executed[0]
    assert sent["name"] == "mine"
    assert sent["set"] == {"a": 1}
    assert sent["fresh"] is True
    assert sent["lineage"].overrides == {"flow.x": 2}
    assert summary["status"] == "completed"
    assert summary["run_dir"] == "/r/case"


def test_run_simulation_names_the_run_after_the_file_stem_without_a_name(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "completed_identical_run", lambda cfg, *, name: None)
    fake_project.cfg_of_a_file = _cfg(tmp_path, name=None)
    wf.run_simulation(tmp_path / "site_a.toml")
    assert fake_project.instances[-1].executed[0]["name"] == "site_a"


def test_run_simulation_returns_an_empty_summary_when_nothing_was_run(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "completed_identical_run", lambda cfg, *, name: None)
    fake_project.result = None
    assert wf.run_simulation(_cfg(tmp_path)) == {}


def test_run_simulation_checks_then_warns_about_a_replayed_run(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        rc, "check_replay", lambda cfg, src, *, project_root, inputs_checked: seen.update(c=src)
    )
    monkeypatch.setattr(rc, "warn_replay_differences", lambda src, run: seen.update(w=(src, run)))
    published = tmp_path / "copy"
    wf.run_simulation(_cfg(tmp_path), replay_of=published)
    assert seen["c"] == published
    assert seen["w"] == (published, Path("/r/case"))
    assert fake_project.instances[0].executed[0]["frozen"] is False


def test_checked_replay_source_is_none_without_a_sealed_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    monkeypatch.setattr(rc, "sealed_run_of", lambda path: None)
    assert wf.checked_replay_source(object(), tmp_path / "a.toml", None, tmp_path) is None
    assert wf.checked_replay_source(object(), None, None, tmp_path) is None


def test_skipped_identical_run_looks_at_the_configuration_with_the_changes_applied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.project.run_overrides as ro

    monkeypatch.setattr(ro, "override_changes", lambda cfg, ch: dict(ch))
    seen: list[Any] = []

    def probe(cfg: Any, *, name: str) -> None:
        seen.append(cfg)

    monkeypatch.setattr(wf, "completed_identical_run", probe)
    assert wf.skipped_identical_run(_cfg(tmp_path), {"x": 1}, "case", str(tmp_path)) is None
    assert seen[0].changed == {"x": 1}


def test_mesh_summary_is_given_only_when_the_plan_runs_a_mesh_process() -> None:
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


def test_identical_run_message_falls_back_to_the_short_id() -> None:
    assert wf.identical_run_message("base", "abcdef123456") == (
        "Config identical to completed run 'base' [abcdef12]; nothing to do."
    )
    assert "'abcdef12' [abcdef12]" in wf.identical_run_message(None, "abcdef123456")


def test_completed_identical_run_is_none_without_a_runs_directory(tmp_path: Path) -> None:
    cfg = SimpleNamespace(workspace=SimpleNamespace(project_root=str(tmp_path)))
    assert wf.completed_identical_run(cfg, name="case") is None


def test_completed_run_view_indexes_then_reads_the_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.project.runner as runner
    import hydromodpy.results.catalog.indexer as indexer

    order: list[Any] = []
    monkeypatch.setattr(indexer, "index_new_runs", lambda root: order.append(("index", root)))
    monkeypatch.setattr(
        runner,
        "run_view_of",
        lambda run_dir, *, project_root, sim_id: order.append(("view", run_dir, sim_id)) or "V",
    )
    summary = {"project_root": str(tmp_path), "name": "case", "sim_id": "sid"}
    assert wf.completed_run_view(summary) == "V"
    assert order[0] == ("index", tmp_path)
    assert order[1][0] == "view"
    assert order[1][1].name == "case"
    assert order[1][2] == "sid"


def _phases_loader(monkeypatch: pytest.MonkeyPatch, names: list[str] | Exception) -> None:
    import hydromodpy.calibration.runners.cli_runner as cli

    def load(path: Path) -> tuple[Any, dict]:
        if isinstance(names, Exception):
            raise names
        return SimpleNamespace(phases=[SimpleNamespace(name=n) for n in names]), {}

    monkeypatch.setattr(cli, "load_toml_calibration", load)


def test_declared_phases_are_listed_and_an_unreadable_file_declares_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _phases_loader(monkeypatch, ["warm", "fine"])
    assert wf.declared_calibration_phases("c.toml") == ["warm", "fine"]
    _phases_loader(monkeypatch, ValueError("bad"))
    assert wf.declared_calibration_phases("c.toml") == []


def test_calibration_phases_or_raise_reports_an_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _phases_loader(monkeypatch, ["warm"])
    assert wf.calibration_phases_or_raise("c.toml") == ["warm"]
    _phases_loader(monkeypatch, ValueError("bad"))
    with pytest.raises(ConfigError, match="cannot be read: bad"):
        wf.calibration_phases_or_raise("c.toml")


def test_no_such_phase_names_the_source_and_the_phase() -> None:
    message = wf.no_such_phase("c.toml", "fine")
    assert "c.toml" in message
    assert "'fine'" in message


@pytest.fixture
def calibration_runners(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import hydromodpy.calibration.preflight as preflight
    import hydromodpy.calibration.runners.cli_runner as cli
    import hydromodpy.calibration.runners.staged_runner as staged

    called: list[str] = []
    monkeypatch.setattr(preflight, "preflight_launch", lambda target: called.append("preflight"))
    monkeypatch.setattr(
        staged,
        "run_staged_calibration",
        lambda target, *, phase: (
            called.append(f"staged:{phase}") or SimpleNamespace(to_dict=lambda: {"kind": "staged"})
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_calibration_cli",
        lambda target: called.append("flat") or SimpleNamespace(to_dict=lambda: {"kind": "flat"}),
    )
    return called


def test_run_calibration_routes_a_phased_file_to_the_staged_runner(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str]
) -> None:
    _phases_loader(monkeypatch, ["warm"])
    assert wf.run_calibration("c.toml", phase="warm") == {"kind": "staged"}
    assert calibration_runners == ["preflight", "staged:warm"]


def test_run_calibration_routes_a_flat_file_to_the_single_runner(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str]
) -> None:
    _phases_loader(monkeypatch, [])
    assert wf.run_calibration("c.toml") == {"kind": "flat"}
    assert calibration_runners == ["preflight", "flat"]


def test_run_calibration_refuses_a_phase_a_flat_file_does_not_declare(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str]
) -> None:
    _phases_loader(monkeypatch, [])
    with pytest.raises(CalibrationError, match="no phase 'warm'"):
        wf.run_calibration("c.toml", phase="warm")


def _draft_collaborators(monkeypatch: pytest.MonkeyPatch, *, is_sites: bool) -> list[Any]:
    import hydromodpy.config.sites.expansion as expansion
    import hydromodpy.workflow.dispatch as wdispatch

    seen: list[Any] = []
    monkeypatch.setattr(wdispatch, "load_raw_toml", lambda path: {"raw": str(path)})
    monkeypatch.setattr(expansion, "is_sites_project", lambda raw: is_sites)
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


def test_a_sites_file_drafts_every_case_of_its_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _draft_collaborators(monkeypatch, is_sites=True)
    path = tmp_path / "sites.toml"
    draft = wf.draft_of_a_file_or_config(
        path, workflow="simulation", set_changes={"flow.recharge": 2}
    )
    assert draft == "PLAN"
    assert seen == [("plan", path, {"flow": {"recharge": 2}})]


def test_an_overview_configuration_drafts_one_case_without_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hydromodpy.display.overview as display_overview

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


def test_a_simulation_configuration_drafts_through_a_dry_run_of_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _draft_collaborators(monkeypatch, is_sites=False)
    seen: dict[str, Any] = {}

    class _Dry(_FakeProject):
        def simulate(self, **kwargs: Any) -> str:
            seen.update(kwargs)
            return "DRY"

    monkeypatch.setattr(project_pkg, "Project", _Dry)
    cfg = SimpleNamespace()
    draft = wf.draft_of_a_file_or_config(
        cfg, workflow="simulation", set_changes={"a": 1}, name="n", from_step="extract"
    )
    assert draft == "DRY"
    assert seen == {
        "dry_run": True,
        "set": {"a": 1},
        "name": "n",
        "resume": None,
        "from_step": "extract",
        "until_step": None,
    }


def test_completed_identical_run_answers_with_the_newest_sealed_version_of_the_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.results.catalog.registration as registration
    import hydromodpy.results.manifest as manifest
    import hydromodpy.results.storage.sealing as sealing

    runs = tmp_path / "runs"
    for name in ("case", "case.v2", "case.v3", "other"):
        (runs / name).mkdir(parents=True)
    (runs / "stray.txt").write_text("x", encoding="utf-8")
    sealed = {"case": "H", "case.v2": "H", "case.v3": "unsealed-or-other", "other": "H"}
    monkeypatch.setattr(registration, "solve_identity_hash", lambda cfg: "H")
    monkeypatch.setattr(sealing, "sealed_config_hash", lambda run_dir: sealed[run_dir.name])
    monkeypatch.setattr(
        manifest, "read_manifest", lambda run_dir: {"run": {"sim_id": f"sid-{run_dir.name}"}}
    )
    cfg = SimpleNamespace(workspace=SimpleNamespace(project_root=str(tmp_path)))
    assert wf.completed_identical_run(cfg, name="case") == ("case.v2", "sid-case.v2")
    sealed["case.v2"] = sealed["case"] = "different"
    assert wf.completed_identical_run(cfg, name="case") is None
    monkeypatch.setattr(registration, "solve_identity_hash", lambda cfg: None)
    assert wf.completed_identical_run(cfg, name="case") is None
