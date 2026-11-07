"""What a program reads from ``hmp``: one envelope, one exit code, one error code.

The contract of ``docs/source/reference/cli/machine-output.md``: under ``--format
json`` stdout holds one object with ``schema`` and ``data``, whatever a library
printed, an empty listing is an empty array, and a failure carries its
``HMPY.Exxx``. The tree is walked so that a new verb falls under the same rules.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import math
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy import cli as cli_package
from hydromodpy.calibration.report import CalibrationReport, CalibrationResult
from hydromodpy.cli.conventions import FORMAT_CHOICES
from hydromodpy.cli.helpers import (
    EXIT_CALIBRATION,
    EXIT_GENERIC,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    EXIT_VALIDATION,
    error_code,
    exit_code_for,
    fail,
)
from hydromodpy.cli.main import _build_parser
from hydromodpy.cli.output import OUTPUTS, emit, output_of, plain, stdout_for_a_program
from hydromodpy.core.exceptions import NothingThereError, SolverDivergedError, StepError
from hydromodpy.core.state.layout import data_cache_path_for
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from tests._helpers.cli_runner import CliRunner
from tests._helpers.run_stores import RUN_NAME, seal_demo_run
from tests.unit.cli._tree import leaves

pytestmark = pytest.mark.fast

COMMANDS_DIR = Path(cli_package.__file__).parent / "commands"

WRITES_A_DOCUMENT = {
    "config template",
    "config resolve",
    "config schema",
    "config wizard",
    "completion",
}
"""What these print is the document itself, so an envelope would break it."""

GONE_FLAGS = {"--json", "--out", "--output", "-o", "--into", "--folder", "--file", "--apply"}


LEAVES = {" ".join(words): parser for words, parser in leaves()}


def _visible_flags(parser: argparse.ArgumentParser) -> set[str]:
    return {
        flag
        for action in parser._actions
        if action.help != argparse.SUPPRESS
        for flag in action.option_strings
    }


@pytest.mark.parametrize("verb", sorted(LEAVES))
def test_a_verb_follows_the_grammar(verb: str) -> None:
    flags = _visible_flags(LEAVES[verb])
    assert "-w" in flags and "--workspace" in flags
    assert not GONE_FLAGS & flags
    assert verb == "export" or "--as" not in flags
    if verb.startswith("dev ") or verb in WRITES_A_DOCUMENT:
        return
    formats = next(a for a in LEAVES[verb]._actions if "--format" in a.option_strings)
    assert tuple(formats.choices) == FORMAT_CHOICES
    assert formats.default == "table"


def _emitted_verbs() -> set[str]:
    """Return the first string of every ``emit(args, "<verb>", ...)`` under ``cli/commands``."""
    found: set[str] = set()
    for path in COMMANDS_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "emit":
                found.add(node.args[1].value)
    return found


def test_each_declared_output_is_written_by_a_verb_that_exists() -> None:
    declared = {output.verb for output in OUTPUTS}
    assert declared == _emitted_verbs()
    stable = {verb for verb in LEAVES if not verb.startswith("dev ")} - WRITES_A_DOCUMENT
    assert stable <= declared, "a verb with --format has no entry in OUTPUTS"
    assert len({output.schema for output in OUTPUTS}) == len(OUTPUTS)


def test_no_command_writes_a_machine_format_by_itself() -> None:
    forbidden = {"dumps", "to_json", "to_csv", "DictWriter"}
    # The JSON Schema `hmp config schema` prints is the document itself.
    offenders = [
        f"{path.relative_to(COMMANDS_DIR)}:{node.lineno}"
        for path in COMMANDS_DIR.rglob("*.py")
        if "dev" not in path.parts and path.name != "config.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr in forbidden
    ]
    assert offenders == []


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project of a workspace, holding one sealed run named ``demo``, indexed."""
    root = tmp_path / "workspace" / "projects" / "demo_project"
    seal_demo_run(root)
    (tmp_path / "workspace" / "data").mkdir()
    return root


READ_VERBS = (
    ("workspace list", []),
    ("project list", []),
    ("project show", []),
    ("site ls", []),
    ("catalog ls", []),
    ("catalog show", [RUN_NAME]),
    ("catalog trash", []),
    ("catalog watch", []),
    ("catalog reindex", []),
    ("catalog gc", []),
    ("catalog tag", [RUN_NAME, "paper"]),
    ("catalog note", [RUN_NAME, "looks right"]),
    ("catalog query", ["SELECT sim_id FROM simulations"]),
    ("catalog diff", [RUN_NAME, RUN_NAME]),
    ("viz list", []),
    ("data ls", []),
    ("example list", []),
    ("doctor", []),
)


@pytest.mark.parametrize(("verb", "words"), READ_VERBS, ids=[row[0] for row in READ_VERBS])
def test_json_is_one_envelope_with_its_schema(project: Path, verb: str, words: list[str]) -> None:
    on_the_workspace = verb in ("project list", "site ls", "data ls")
    where = project.parent.parent if on_the_workspace else project
    result = CliRunner().invoke([*verb.split(), *words, "-w", str(where), "--format", "json"])
    assert result.exit_code == 0, result.stderr

    document = json.loads(result.stdout)
    output = output_of(verb)
    assert set(document) == {"schema", "data"}
    assert document["schema"] == output.schema
    if output.rows:
        assert isinstance(document["data"], list)
    else:
        assert set(document["data"]) == set(output.fields)


@pytest.mark.parametrize("words", [["project", "list"], ["workspace", "list"], ["site", "ls"]])
def test_an_empty_listing_is_an_empty_document(tmp_path: Path, words: list[str]) -> None:
    (tmp_path / "projects").mkdir()
    (tmp_path / "data").mkdir()
    verb = " ".join(words)

    as_json = CliRunner().invoke([*words, "-w", str(tmp_path), "--format", "json"])
    as_csv = CliRunner().invoke([*words, "-w", str(tmp_path), "--format", "csv"])

    assert as_json.exit_code == 0, as_json.stderr
    assert json.loads(as_json.stdout) == {"schema": output_of(verb).schema, "data": []}
    assert next(csv.reader(io.StringIO(as_csv.stdout))) == list(output_of(verb).fields)


def test_w_is_read_before_the_verb_and_the_one_after_it_wins(project: Path) -> None:
    before = CliRunner().invoke(["-w", str(project), "catalog", "ls", "--format", "json"])
    assert [row["name"] for row in json.loads(before.stdout)["data"]] == [RUN_NAME]

    both = CliRunner().invoke(
        ["-w", "/nowhere", "catalog", "ls", "-w", str(project), "--format", "json"]
    )
    assert both.exit_code == 0, both.stderr


def test_emit_holds_what_is_declared_and_writes_strict_json(capsys, tmp_path: Path) -> None:
    args = argparse.Namespace(format="json")
    emit(args, "catalog note", {"rel_dir": tmp_path, "text": math.nan, "extra": 1})
    assert json.loads(capsys.readouterr().out)["data"] == {"rel_dir": str(tmp_path), "text": None}

    frame = pd.DataFrame({"sim_id": ["a"], "name": [None], "other": [1], "nse": [math.inf]})
    emit(args, "catalog query", frame)
    assert json.loads(capsys.readouterr().out)["data"] == [
        {"sim_id": "a", "name": None, "other": 1, "nse": None}
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (pd.NaT, None),
        (pd.NA, None),
        (float("-inf"), None),
        (np.float64(1.5), 1.5),
        (np.array([1, 2]), [1, 2]),
        (pd.Timestamp("2002-10-15"), "2002-10-15T00:00:00"),
        ({"a": (1, {float("nan")})}, {"a": [1, [None]]}),
    ],
)
def test_plain_leaves_nothing_json_refuses(value: object, expected: object) -> None:
    assert plain(value) == expected


def test_csv_writes_the_rows_or_key_value_lines(capsys) -> None:
    args = argparse.Namespace(format="csv")
    emit(args, "project list", [{"name": "a", "run_tomls": ["x.toml", "y.toml"]}])
    assert capsys.readouterr().out.splitlines() == [
        "name,path,has_project_toml,run_tomls",
        "a,,,x.toml;y.toml",
    ]
    emit(args, "project new", {"path": "/p"})
    assert capsys.readouterr().out.splitlines() == ["key,value", "path,/p"]


def test_nothing_printed_while_a_verb_works_reaches_stdout(capfd) -> None:
    args = argparse.Namespace(format="json")

    with stdout_for_a_program(args):
        print("a library that prints")
        os.write(1, b"a solver that prints\n")
        emit(args, "project new", {"path": "/p"})

    captured = capfd.readouterr()
    assert json.loads(captured.out)["data"] == {"path": "/p"}
    assert "a library that prints" in captured.err and "a solver that prints" in captured.err


def test_a_failure_prints_its_code_and_under_json_its_envelope(tmp_path: Path) -> None:
    missing = str(tmp_path / "absent.toml")

    table = CliRunner().invoke(["run", missing])
    as_json = CliRunner().invoke(["run", missing, "--format", "json"])

    assert table.exit_code == as_json.exit_code == EXIT_NOT_FOUND
    assert table.stderr.startswith(f"{NothingThereError.code}: File not found")
    assert table.stdout == ""
    document = json.loads(as_json.stdout)
    assert document["schema"] == "hmp.error.v1"
    assert document["data"]["code"] == NothingThereError.code
    assert document["data"]["exit_code"] == EXIT_NOT_FOUND
    assert missing in document["data"]["detail"]


def test_a_result_already_written_is_not_followed_by_an_error_document(
    project: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "copy"
    assert CliRunner().invoke(["publish", RUN_NAME, "--to", str(copy), "-w", str(project)]).ok
    (copy / "added.txt").write_text("not in PUBLICATION.json", encoding="utf-8")

    result = CliRunner().invoke(["publish", "--verify", str(copy), "--format", "json"])

    assert result.exit_code == EXIT_GENERIC
    document = json.loads(result.stdout)
    assert document["schema"] == "hmp.publish.verify.v1"
    assert any("added.txt" in line for line in document["data"]["problems"])


def test_a_dry_run_of_a_file_is_a_document_too(tmp_path: Path) -> None:
    file = tmp_path / "run.toml"
    file.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    result = CliRunner().invoke(["run", str(file), "--dry-run", "--format", "json"])

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)["data"]
    assert data["workflow"] == "simulation" and data["dry_run"] is True
    assert data["result"]["steps"]


def test_a_mistake_on_the_command_line_carries_a_code_too() -> None:
    result = CliRunner().invoke(["catalog", "ls", "--format", "yaml"])
    assert result.exit_code == EXIT_USAGE
    assert "HMPY.E001: " in result.stderr and "invalid choice" in result.stderr


def test_an_interruption_exits_130_and_carries_no_code(capsys) -> None:
    with pytest.raises(SystemExit) as stopped:
        fail(KeyboardInterrupt())
    assert stopped.value.code == 130
    assert capsys.readouterr().err == "Interrupted.\n"


def test_the_code_of_a_step_is_the_code_of_its_cause() -> None:
    wrapped = StepError("step", cause=SolverDivergedError("diverged"))
    assert error_code(wrapped) == SolverDivergedError.code
    assert error_code(FileNotFoundError("x")) == NothingThereError.code
    assert error_code(ValueError("x")) == "HMPY.E000"
    assert exit_code_for(NothingThereError("x")) == EXIT_NOT_FOUND


def _report(**fields: object) -> CalibrationReport:
    base = dict(
        session_id="s",
        method="optuna",
        n_trials=3,
        best_cost=0.25,
        duration_s=1.0,
        save_runs="best_n",
        promoted=1,
        best_parameters={"K": 2e-4},
    )
    return CalibrationReport(**{**base, **fields})


def _calibrate(monkeypatch, tmp_path: Path, report: CalibrationReport, *flags: str):
    import hydromodpy as hmp

    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    monkeypatch.setattr(hmp, "calibrate", lambda *a, **k: report)
    return CliRunner().invoke(["calibrate", str(config), "--format", "json", *flags])


def test_calibrate_writes_a_payload_its_schema_describes(monkeypatch, tmp_path: Path) -> None:
    phase_report = _report(best_cost=float("nan"))
    from hydromodpy.calibration.report import PhaseRun

    report = _report(
        phases=(PhaseRun(name="p", index=0, session_id="s", report=phase_report, frozen=()),),
        extra={"cost_metric": "nse"},
    )

    result = _calibrate(monkeypatch, tmp_path, report)

    assert result.exit_code == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["schema"] == "hmp.calibrate.v1"
    assert document["data"]["best_parameters"] == {"K": 2e-4}
    assert document["data"]["phases"][0]["report"]["best_cost"] is None
    assert CalibrationResult.model_validate(document["data"])
    assert set(output_of("calibrate").fields) == set(CalibrationResult.model_fields)
    assert output_of("calibrate").experimental


def test_calibrate_writes_the_payload_of_a_session_read_from_disk(
    monkeypatch, tmp_path: Path
) -> None:
    import jsonschema

    from hydromodpy import schema
    from hydromodpy.results.session.descriptor import read_session, write_session
    from tests._helpers.session_documents import best_trial, calibration_window, session_descriptor

    directory = tmp_path / "project" / "sessions" / "case"
    directory.mkdir(parents=True)
    write_session(
        directory,
        session_descriptor(
            best=best_trial(3, cost=0.4, rel_dir="runs/case", parameters={"K": 3e-5}),
            status="completed",
            windows=calibration_window(date(2000, 1, 1), date(2001, 12, 31)),
        ),
    )
    stored = read_session(directory)
    best = stored.best
    report = _report(
        session_id=stored.session_id,
        method=stored.method,
        status=stored.status,
        best_cost=best.cost,
        best_trial=best.trial,
        best_parameters=dict(best.parameters),
        best_cases=dict(best.cases),
        windows=dict(stored.windows),
        workspace=directory.parent.parent,
        session_dir=directory,
    )

    result = _calibrate(monkeypatch, tmp_path, report)

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)["data"]
    document = Path(schema.__file__).parent / "results" / "calibrate.v1.json"
    jsonschema.validate(data, json.loads(document.read_text(encoding="utf-8")))
    assert data["best_cases"]["case"]["rel_dir"] == "runs/case"
    assert data["windows"]["calibration"]["start"] == "2000-01-01"
    assert data["session_dir"] == str(directory)


def test_an_unfinished_session_keeps_its_result_and_its_exit_code(
    monkeypatch, tmp_path: Path
) -> None:
    report = _report(extra={"promotion_failures": ["trial 1: no space left"]})

    result = _calibrate(monkeypatch, tmp_path, report)

    assert result.exit_code == EXIT_CALIBRATION
    assert json.loads(result.stdout)["schema"] == "hmp.calibrate.v1"
    assert "trial 1: no space left" in result.stderr


def test_a_preview_changes_nothing_and_y_does(project: Path) -> None:
    (project / "runs" / "second").mkdir(parents=True)
    run_dir = project / "runs" / RUN_NAME

    for words in (
        ["catalog", "delete", RUN_NAME, "--dry-run", "-y"],
        ["catalog", "delete", RUN_NAME, "--now", "--dry-run", "-y"],
        ["privacy", "purge", RUN_NAME, "--dry-run"],
        ["catalog", "trash", "--empty", "--dry-run"],
    ):
        result = CliRunner().invoke([*words, "-w", str(project), "--format", "json"])
        assert result.exit_code == 0, (words, result.stderr)
        assert json.loads(result.stdout)["data"]["applied"] is False
        assert run_dir.is_dir(), words

    done = CliRunner().invoke(
        ["catalog", "delete", RUN_NAME, "-y", "-w", str(project), "--format", "json"]
    )
    assert json.loads(done.stdout)["data"]["applied"] is True
    assert not run_dir.exists()


def test_a_removal_without_y_is_refused_when_nobody_can_answer(project: Path) -> None:
    result = CliRunner().invoke(["catalog", "trash", "--empty", "-w", str(project)])
    assert result.exit_code == EXIT_USAGE
    assert "-y" in result.stderr


def test_lock_verify_reports_each_mismatch_and_exits_on_the_validation_code(monkeypatch) -> None:
    mismatch = SimpleNamespace(
        kind="missing", variable="dem", source="ign", station_id=None, path="x"
    )
    result = {
        "ok": False,
        "mismatches": [mismatch],
        "schema_diverged": False,
        "locked_schema": "a",
        "current_schema": "a",
    }
    monkeypatch.setattr("hydromodpy.project.lock.lock_verify", lambda *a, **k: result)

    table = CliRunner().invoke(["lock", "verify"])

    assert table.exit_code == EXIT_VALIDATION
    assert "[missing] dem/ign/None -> x" in table.stdout


def test_config_check_says_which_workspace_the_file_resolves_to(project: Path) -> None:
    file = project / "run.toml"
    file.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    result = CliRunner().invoke(["config", "check", str(file), "--format", "json"])

    names = [check["name"] for check in json.loads(result.stdout)["data"]["workspace"]]
    assert {"workspace", "catalog_path", "data_dir", "runs_dir"} <= set(names)


def test_a_cache_entry_is_counted_and_kept_under_dry_run(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "projects").mkdir()
    served = tmp_path / "data" / "dem.tif"
    served.write_bytes(b"x")
    with DataCatalogDuckDB(data_cache_path_for(tmp_path / "data")) as catalog:
        catalog.register(variable="dem", source="ign", station_id=None, file_path=str(served))

    for words in (
        ["data", "remove", "--variable", "dem", "--dry-run"],
        ["data", "prune", "--older-than", "0", "--dry-run"],
    ):
        result = CliRunner().invoke([*words, "-w", str(tmp_path), "--format", "json"])
        assert result.exit_code == 0, result.stderr
        data = json.loads(result.stdout)["data"]
        assert data["applied"] is False

    with DataCatalogDuckDB(data_cache_path_for(tmp_path / "data")) as catalog:
        assert catalog.backend.fetch_all("SELECT count(*) FROM entries") == [(1,)]


_SPINUP_TOML = """\
[workflow]
mode = "simulation"

[site]
name = "nancon"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 385000.0
y_outlet = 6814000.0
dem_init_path = "dem.tif"
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[spinup]
max_cycles = 3
"""


def _disk_state(root: Path) -> dict[str, tuple[int, int]]:
    """Return every file and directory under *root* with its size and modification time."""
    state = {}
    for path in sorted(root.rglob("*")):
        info = path.stat()
        state[str(path.relative_to(root))] = (
            0 if path.is_dir() else info.st_size,
            info.st_mtime_ns,
        )
    return state


def test_every_verb_that_writes_has_a_dry_run_that_changes_nothing(
    project: Path, tmp_path: Path
) -> None:
    workspace = project.parent.parent
    other = tmp_path / "other"
    (other / "data").mkdir(parents=True)
    (other / "projects").mkdir()
    (project / "runs" / RUN_NAME / "config.toml").write_text('[site]\nname = "x"\n', "utf-8")
    old_key = tmp_path / "old.toml"
    old_key.write_text('[simulation]\nrun_id = "cheze"\n', encoding="utf-8")
    plain = tmp_path / "spin.toml"
    plain.write_text(_SPINUP_TOML, encoding="utf-8")
    copy, package, ws = tmp_path / "copy", tmp_path / "pkg.tar", str(project)
    second = workspace / "projects" / "second"
    seal_demo_run(second, "elsewhere")

    def invoke(*words: str):
        return CliRunner().invoke([*words, "--format", "json"])

    assert invoke("publish", RUN_NAME, "--to", str(copy), "-w", ws).exit_code == 0
    assert invoke("publish", "--package", "--to", str(package), "-w", ws).exit_code == 0
    seal_demo_run(project, "trashed")
    assert invoke("catalog", "delete", "trashed", "-y", "-w", ws).exit_code == 0

    cases = (
        (["publish", RUN_NAME, "--to", str(tmp_path / "new"), "-w", ws], "copies"),
        (["publish", ".", "--to", str(tmp_path / "new"), "-w", ws], "copies"),
        (["publish", "--package", "--to", str(tmp_path / "new.tar"), "-w", ws], "copies"),
        (["catalog", "rename", RUN_NAME, "renamed", "-w", ws], "renamed"),
        (["catalog", "restore", "trashed", "-w", ws], "rel_dir"),
        (["catalog", "rerun", RUN_NAME, "-w", ws], "rel_dir"),
        (["catalog", "import", str(copy), "--name", "back", "-w", str(second)], "rel_dir"),
        (["project", "import", str(package), "-w", str(other)], "project"),
        (["spinup", str(plain), "-w", str(workspace)], "n_cycles"),
        (["doctor", "--fix-config", str(old_key)], None),
    )
    for words, key in cases:
        before = _disk_state(tmp_path)
        result = invoke(*words, "--dry-run")
        assert result.exit_code == 0, (words, result.stderr)
        assert _disk_state(tmp_path) == before, words
        if key is not None:
            data = json.loads(result.stdout)["data"]
            assert data["applied"] is False, words
            assert key in data, words

    table = CliRunner().invoke(["doctor", "--fix-config", str(old_key), "--dry-run"])
    assert "-run_id" in table.stdout and "+name" in table.stdout
