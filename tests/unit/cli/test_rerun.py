"""``hmp catalog rerun`` reads the frozen config.toml of a run (provider mocked; no solve)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

import hydromodpy
from hydromodpy.cli.commands.catalog import rerun as rerun_cmd
from hydromodpy.results.run import rerun_contract
from tests._helpers.sealed_runs import manifest_document

SOURCE_ID = "9a4f0c1e-0000-4000-8000-000000000001"
NEW_ID = "7b1e0000-0000-4000-8000-000000000002"


@pytest.fixture
def restore_provider():
    hydromodpy.bootstrap()
    original = rerun_contract._provider
    try:
        yield
    finally:
        rerun_contract.register_rerun_provider(original)


def _hmp(monkeypatch, *argv: str) -> int:
    main = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", ["hmp", *argv])
    try:
        main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    run_dir = project / "runs" / "nancon_monthly.v2"
    run_dir.mkdir(parents=True)
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    (run_dir / "config.toml").write_text(
        '[simulation]\nname = "nancon_monthly"\n[flow]\nk = 1e-5\n', encoding="utf-8"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest_document(sim_id=SOURCE_ID)),
        encoding="utf-8",
    )
    return project


def test_parse_overrides_coerces_types() -> None:
    assert rerun_cmd._parse_overrides(
        ["flow.K=2e-4", "sim.flag=true", "n=5", "a=[1, 2]", 's="007"', "label=plain"]
    ) == {
        "flow.K": 2e-4,
        "sim.flag": True,
        "n": 5,
        "a": [1, 2],
        "s": "007",
        "label": "plain",
    }


def test_rerun_reads_the_frozen_config_and_keeps_the_name(
    tmp_path: Path, monkeypatch, capsys, restore_provider
) -> None:
    project = _project(tmp_path)
    calls: dict = {}

    class MockProvider:
        def rerun(self, snapshot, *, overrides, name, source_sim_id=None, source_dir=None):
            calls.update(
                overrides=dict(overrides),
                name=name,
                snapshot=snapshot,
                source=source_sim_id,
                source_dir=source_dir,
            )
            new_dir = project / "runs" / "nancon_monthly.v3"
            new_dir.mkdir()
            (new_dir / "manifest.json").write_text(
                json.dumps(manifest_document(sim_id=NEW_ID)),
                encoding="utf-8",
            )
            return NEW_ID

    rerun_contract.register_rerun_provider(MockProvider())
    code = _hmp(
        monkeypatch,
        "catalog",
        "rerun",
        "nancon_monthly.v2",
        "--set",
        "flow.k=2e-4",
        "-w",
        str(project),
    )

    assert code == 0
    assert calls["name"] == "nancon_monthly"
    assert calls["source"] == SOURCE_ID
    assert calls["source_dir"] == project.resolve() / "runs" / "nancon_monthly.v2"
    assert calls["overrides"] == {"flow.k": 2e-4}
    assert calls["snapshot"]["flow"]["k"] == 1e-5
    assert calls["snapshot"]["workspace"]["project_root"] == str(project.resolve())
    assert "runs/nancon_monthly.v3" in capsys.readouterr().out
    assert not (project / ".hmp" / "index.duckdb").exists()


def test_rerun_without_a_frozen_config_is_refused(
    tmp_path: Path, monkeypatch, capsys, restore_provider
) -> None:
    project = _project(tmp_path)
    (project / "runs" / "nancon_monthly.v2" / "config.toml").unlink()

    code = _hmp(monkeypatch, "catalog", "rerun", "nancon_monthly.v2", "-w", str(project))

    assert code != 0
    assert "config.toml" in capsys.readouterr().err


def test_the_provider_seals_the_child_as_a_rerun_of_its_source(monkeypatch) -> None:
    """``ProjectRerunProvider`` hands ``simulate`` a lineage naming the source."""
    import types

    import hydromodpy.project as project_module
    from hydromodpy.project.dispatch.rerun import ProjectRerunProvider

    seen: dict = {}

    class _Project:
        def __init__(self, config) -> None:
            self.config = config
            self._ctx = types.SimpleNamespace(parent_sim_id=None)

        def simulate(self, *, name, lineage):
            seen.update(
                name=name,
                lineage=lineage,
                parent=self._ctx.parent_sim_id,
                k=self.config["flow"]["k"],
            )
            return types.SimpleNamespace(sim_id=NEW_ID)

    monkeypatch.setattr(project_module, "Project", _Project)
    from hydromodpy.config import HydroModPyConfig

    monkeypatch.setattr(
        HydroModPyConfig,
        "from_snapshot",
        classmethod(lambda cls, s, changes=None: {"flow": {"k": changes["flow.k"]}}),
    )

    new_id = ProjectRerunProvider().rerun(
        {"flow": {"k": 1e-5}},
        overrides={"flow.k": 2e-4},
        name="nancon_monthly",
        source_sim_id=SOURCE_ID,
    )

    assert new_id == NEW_ID
    assert seen["lineage"].kind == "rerun"
    assert seen["lineage"].parent_sim_id == SOURCE_ID
    assert seen["lineage"].overrides == {"flow.k": 2e-4}
    assert seen["parent"] == SOURCE_ID
    assert seen["k"] == 2e-4
    assert seen["name"] == "nancon_monthly"
