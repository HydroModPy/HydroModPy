"""The result tables a run no longer reads are migrated, never carried over.

``[simulation.results.derived]`` and ``[simulation.results.budget]`` switched
which fields a run kept. A run now keeps its whole per-cell budget and rebuilds
every derived field on read, so both tables go whatever they hold, at the root
and under every comparison or testbed overlay.

The tests assert what the migrated document holds, never what the model
accepts, so they hold once the model refuses the old tables.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import (
    RETIRED_RESULTS_TABLES,
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
)
from hydromodpy.config.stored_config_migration import migrate_stored_config

_FIXTURES = Path(__file__).parent / "fixtures" / "stored_e611edf79"
_RETIRED = ("derived", "budget")


def _results_with_both_tables(spatial_fields: bool) -> dict[str, Any]:
    return {
        "keep_solver_files": True,
        "derived": {"watertable_depth": True, "release_flux": False},
        "budget": {"spatial_fields": spatial_fields},
    }


def _overlaid_doc(spatial_fields: bool = True) -> dict[str, Any]:
    """Return a document holding both tables in every place an overlay can."""

    def overlay() -> dict[str, Any]:
        return {"simulation": {"results": _results_with_both_tables(spatial_fields)}}

    return {
        "simulation": {"name": "cheze", "results": _results_with_both_tables(spatial_fields)},
        "comparison": {
            "base_simulation_overlay": overlay(),
            "simulation": [{"id": "a", "overlay": overlay()}, {"id": "b", "overlay": overlay()}],
        },
        "testbed": {
            "case": [{"id": "c", "overlay": overlay()}],
            "case_from_catalog": [{"id_template": "{site}", "overlay": overlay()}],
        },
    }


def _every_results_table(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``[simulation.results]`` table of the root and of every overlay."""
    scopes = [doc]
    scopes.append(doc["comparison"]["base_simulation_overlay"])
    scopes.extend(entry["overlay"] for entry in doc["comparison"]["simulation"])
    scopes.extend(entry["overlay"] for entry in doc["testbed"]["case"])
    scopes.extend(entry["overlay"] for entry in doc["testbed"]["case_from_catalog"])
    return [scope["simulation"]["results"] for scope in scopes]


def _migration_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if "migrated" in record.getMessage()]


def test_the_constant_names_the_two_tables() -> None:
    assert RETIRED_RESULTS_TABLES == ("simulation.results.derived", "simulation.results.budget")


@pytest.mark.parametrize("spatial_fields", [True, False])
def test_a_stored_config_loses_both_tables_at_the_root_and_in_every_overlay(
    spatial_fields: bool,
) -> None:
    payload = _overlaid_doc(spatial_fields)

    stored = migrate_stored_config(payload)

    tables = _every_results_table(stored)
    assert len(tables) == 6
    for results in tables:
        assert not set(_RETIRED) & set(results)
        assert results == {"keep_solver_files": True}
    assert "spatial_fields" not in json.dumps(stored)
    assert "keep_per_cell_budget" not in json.dumps(stored)
    # The payload handed in is left as it was.
    assert "derived" in payload["simulation"]["results"]


def test_a_stored_config_logs_one_line_naming_what_it_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="hydromodpy"):
        migrate_stored_config(_overlaid_doc(), source="runs/frozen/config.toml")

    lines = _migration_records(caplog)
    assert len(lines) == 1
    assert "runs/frozen/config.toml" in lines[0]
    assert "simulation.results.derived" in lines[0]
    assert "simulation.results.budget" in lines[0]
    assert "comparison.base_simulation_overlay.simulation.results.derived" in lines[0]
    assert "hmp doctor" not in lines[0]


def test_a_current_stored_config_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="hydromodpy"):
        stored = migrate_stored_config({"simulation": {"results": {"keep_solver_files": True}}})

    assert stored == {"simulation": {"results": {"keep_solver_files": True}}}
    assert caplog.records == []


def test_the_stored_fixtures_carry_the_tables_and_load_with_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    snapshot = json.loads((_FIXTURES / "snapshot_modflow_nwt.json").read_text(encoding="utf-8"))
    results = snapshot["simulation"]["results"]
    assert results["budget"] == {"spatial_fields": False}
    assert "derived" in results

    with caplog.at_level(logging.INFO, logger="hydromodpy"), warnings.catch_warnings():
        warnings.simplefilter("error")
        cfg = HydroModPyConfig.from_snapshot(snapshot)

    assert cfg.simulation.name
    lines = _migration_records(caplog)
    assert len(lines) == 1
    assert "simulation.results.derived" in lines[0]
    assert "simulation.results.budget" in lines[0]
    assert not [record for record in caplog.records if record.levelno > logging.INFO]


def test_the_checkpoint_payload_loses_the_tables() -> None:
    checkpoint = json.loads(
        (_FIXTURES / "resolved_config_modflow_nwt.json").read_text(encoding="utf-8")
    )["config"]
    assert "derived" in checkpoint["simulation"]["results"]

    stored = migrate_stored_config(checkpoint, source="checkpoint resolved config")

    assert not set(_RETIRED) & set(stored["simulation"]["results"])


def test_a_user_file_is_migrated_with_the_message_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc = _overlaid_doc()

    with caplog.at_level(logging.INFO, logger="hydromodpy"):
        changes = migrate_config_doc_on_load(doc, source="project.toml")

    for results in _every_results_table(doc):
        assert not set(_RETIRED) & set(results)
    assert len(changes) == 1
    assert "keep_per_cell_budget = false" in changes[0]
    assert "whole per-cell budget" in changes[0]
    assert "rebuilds every derived field on read" in changes[0]
    for place in (
        "simulation.results.derived",
        "simulation.results.budget",
        "comparison.base_simulation_overlay.simulation.results.derived",
        "comparison.simulation[1].overlay.simulation.results.budget",
        "testbed.case[0].overlay.simulation.results.derived",
        "testbed.case_from_catalog[0].overlay.simulation.results.budget",
    ):
        assert place in changes[0]

    lines = _migration_records(caplog)
    assert len(lines) == 1
    assert "hmp doctor --fix-config project.toml" in lines[0]
    assert "keep_per_cell_budget = false" in lines[0]


def test_a_user_file_without_the_tables_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    doc = {"simulation": {"name": "cheze", "results": {"keep_solver_files": True}}}

    with caplog.at_level(logging.INFO, logger="hydromodpy"):
        assert migrate_config_doc(doc) == []

    assert caplog.records == []


def test_a_single_comparison_table_migrates_like_an_array_of_one() -> None:
    doc = {
        "comparison": {
            "simulation": {"id": "a", "overlay": {"simulation": {"results": {"derived": {}}}}}
        }
    }

    changes = migrate_config_doc(doc)

    assert doc["comparison"]["simulation"]["overlay"]["simulation"]["results"] == {}
    assert "comparison.simulation[0].overlay.simulation.results.derived" in changes[0]


def test_an_overlay_without_a_results_table_is_left_alone() -> None:
    doc = {
        "comparison": {
            "base_simulation_overlay": {"simulation": {"name": "x"}},
            "simulation": [{"id": "a"}, {"id": "b", "overlay": {"flow": {}}}],
        },
        "testbed": {"case": [{"id": "c", "overlay": None}]},
    }
    before = copy.deepcopy(doc)

    assert migrate_config_doc(doc) == []
    assert doc == before


def test_the_doctor_rewrites_the_file_without_the_tables(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        "# the project\n"
        '[simulation]\nname = "cheze"\n\n'
        "[simulation.results]\nkeep_solver_files = true # keep the raw files\n\n"
        "[simulation.results.derived]\nwatertable_depth = true\n\n"
        "[simulation.results.budget]\nspatial_fields = true\n\n"
        '[[comparison.simulation]]\nid = "a"\n'
        "[comparison.simulation.overlay.simulation.results.derived]\nrelease_flux = true\n\n"
        '[[testbed.case]]\nid = "c"\n'
        "[testbed.case.overlay.simulation.results.budget]\nspatial_fields = false\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert len(changes) == 1
    text = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    assert parsed["simulation"]["results"] == {"keep_solver_files": True}
    assert parsed["comparison"]["simulation"][0]["id"] == "a"
    assert parsed["testbed"]["case"][0]["id"] == "c"
    assert "derived" not in text
    assert "spatial_fields" not in text
    assert "# the project" in text
    assert "# keep the raw files" in text
    assert fix_config_file(path) == []


def test_a_user_project_file_holding_the_tables_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "project.toml"
    document = tomlkit.parse((_FIXTURES / "config_modflow_nwt.toml").read_text(encoding="utf-8"))
    del document["persistence"]
    del document["solver"]["backend"]
    path.write_text(tomlkit.dumps(document), encoding="utf-8")
    assert "derived" in document["simulation"]["results"]

    with caplog.at_level(logging.INFO, logger="hydromodpy"):
        cfg = HydroModPyConfig.from_toml(path)

    assert cfg.solver.backend_name == "modflow_nwt"
    lines = _migration_records(caplog)
    assert len(lines) == 1
    assert f"hmp doctor --fix-config {path}" in lines[0]
    assert "simulation.results.derived" in lines[0]
    assert "simulation.results.budget" in lines[0]
    assert "dropped" in lines[0]


def _phase_overrides_doc() -> dict[str, Any]:
    return {
        "calibration": {
            "phases": [
                {"name": "p0", "overrides": {"flow.flow_regime": "steady"}},
                {
                    "name": "p1",
                    "overrides": {
                        "simulation.results.budget.spatial_fields": True,
                        "simulation.results.derived": {"seepage_areas": True},
                        "simulation.results.keep_solver_files": True,
                        "display.overrides.map.time": "last",
                    },
                },
            ]
        }
    }


def test_a_calibration_phase_loses_the_retired_tables_it_overrides() -> None:
    doc = _phase_overrides_doc()

    changes = migrate_config_doc(doc)

    assert doc["calibration"]["phases"][0]["overrides"] == {"flow.flow_regime": "steady"}
    assert doc["calibration"]["phases"][1]["overrides"] == {
        "simulation.results.keep_solver_files": True,
        "display.overrides.map.time": "last",
    }
    assert len(changes) == 1
    assert (
        'calibration.phases[1].overrides."simulation.results.budget.spatial_fields"' in changes[0]
    )
    assert 'calibration.phases[1].overrides."simulation.results.derived"' in changes[0]
    assert "keep_per_cell_budget = false" in changes[0]


def test_a_calibration_phase_with_nested_override_tables_loses_them_too() -> None:
    doc = {
        "calibration": {
            "phases": {
                "name": "p",
                "overrides": {"simulation": {"results": {"budget": {"spatial_fields": True}}}},
            }
        }
    }

    changes = migrate_config_doc(doc)

    assert doc["calibration"]["phases"]["overrides"] == {"simulation": {"results": {}}}
    assert "calibration.phases[0].overrides.simulation.results.budget" in changes[0]


def test_the_doctor_drops_the_phase_overrides_and_keeps_the_comments(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        "# the project\n"
        "[[calibration.phases]]\n"
        'name = "p"\n'
        "[calibration.phases.overrides]\n"
        '"simulation.results.budget.spatial_fields" = true # old switch\n'
        '"flow.flow_regime" = "steady" # keep me\n',
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert len(changes) == 1
    text = path.read_text(encoding="utf-8")
    assert tomllib.loads(text)["calibration"]["phases"][0]["overrides"] == {
        "flow.flow_regime": "steady"
    }
    assert "spatial_fields" not in text
    assert "# the project" in text
    assert "# keep me" in text
    assert fix_config_file(path) == []


_SPLIT_TABLES = (
    "# the project\n"
    "[simulation.results.derived]\n"
    "seepage_areas = true # old\n"
    "[flow]\n"
    "x = 1 # keep me\n"
    "[simulation.results.budget]\n"
    "spatial_fields = true\n"
)
_DOTTED_KEYS = (
    "# the project\n"
    "[simulation]\n"
    'name = "cheze" # keep me\n'
    "results.derived.seepage_areas = true\n"
    "results.budget.spatial_fields = true\n"
)


@pytest.mark.parametrize(
    ("source", "kept"),
    [(_SPLIT_TABLES, "# keep me"), (_DOTTED_KEYS, "# keep me")],
    ids=["split-tables", "dotted-keys"],
)
def test_the_doctor_rewrites_a_file_whose_tables_are_out_of_order(
    tmp_path: Path, source: str, kept: str
) -> None:
    path = tmp_path / "project.toml"
    path.write_text(source, encoding="utf-8")

    changes = fix_config_file(path)

    assert len(changes) == 1
    assert "simulation.results.derived" in changes[0]
    assert "simulation.results.budget" in changes[0]
    text = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    assert not set(_RETIRED) & set(parsed.get("simulation", {}).get("results", {}))
    assert "derived" not in text
    assert "spatial_fields" not in text
    assert "# the project" in text
    assert kept in text
    assert fix_config_file(path) == []


def test_a_sealed_run_config_gets_the_stored_line_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_dir = tmp_path / "proj" / "runs" / "frozen_nwt"
    run_dir.mkdir(parents=True)
    sealed = run_dir / "config.toml"
    shutil.copy(_FIXTURES / "config_modflow_nwt.toml", sealed)

    with caplog.at_level(logging.INFO, logger="hydromodpy"), warnings.catch_warnings():
        warnings.simplefilter("error")
        cfg = HydroModPyConfig.from_toml(sealed)

    assert cfg.solver.backend_name == "modflow_nwt"
    lines = _migration_records(caplog)
    assert len(lines) == 1
    assert "removed since the run was stored" in lines[0]
    assert "simulation.results.derived" in lines[0]
    assert "simulation.results.budget" in lines[0]
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "keep_per_cell_budget" not in text
    assert "hmp doctor" not in text


def test_a_rerun_reads_the_snapshot_through_the_stored_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hydromodpy.project as project_module
    from hydromodpy.project.dispatch.rerun import ProjectRerunProvider

    seen: list[dict[str, Any]] = []

    class _Stop(Exception):
        pass

    def fake_project(payload: dict[str, Any]) -> None:
        seen.append(payload)
        raise _Stop

    monkeypatch.setattr(project_module, "Project", fake_project)
    snapshot = json.loads((_FIXTURES / "snapshot_modflow_nwt.json").read_text(encoding="utf-8"))

    with pytest.raises(_Stop):
        ProjectRerunProvider().rerun(snapshot, overrides={}, name=None, source_sim_id="abcdef123")

    assert not set(_RETIRED) & set(seen[0]["simulation"]["results"])
    assert "persistence" not in seen[0]
