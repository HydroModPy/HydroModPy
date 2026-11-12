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
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy import cli as cli_package
from hydromodpy.calibration.report import CalibrationReport, CalibrationResult
from hydromodpy.cli.conventions import FORMAT_CHOICES
from hydromodpy.cli.exit_codes import (
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
from hydromodpy.cli.output import (
    OUTPUTS,
    emit,
    output_of,
    plain,
    print_table,
    stdout_for_a_program,
    table_cell,
)
from hydromodpy.core.exceptions import NothingThereError, SolverDivergedError, StepError
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.project.data_cache import DataLock
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
def test_verb_grammar(verb: str) -> None:
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
    found: set[str] = set()
    for path in COMMANDS_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "emit":
                found.add(node.args[1].value)
    return found


def test_declared_outputs() -> None:
    declared = {output.verb for output in OUTPUTS}
    assert declared == _emitted_verbs()
    stable = {verb for verb in LEAVES if not verb.startswith("dev ")} - WRITES_A_DOCUMENT
    assert stable <= declared, "a verb with --format has no entry in OUTPUTS"
    assert len({output.schema for output in OUTPUTS}) == len(OUTPUTS)


def test_no_hand_written_format() -> None:
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
    # A project of a workspace, holding one sealed run named demo, indexed.
    root = tmp_path / "workspace" / "projects" / "demo_project"
    seal_demo_run(root)
    (tmp_path / "workspace" / "data").mkdir()
    return root


READ_VERBS = (
    ("workspace list", []),
    ("project list", []),
    ("show project", ["show", "."]),
    ("site ls", []),
    ("ls", ["ls"]),
    ("ls disk", ["ls", "--disk"]),
    ("show run", ["show", RUN_NAME]),
    ("show profile", ["show", RUN_NAME, "--profile"]),
    ("catalog trash", []),
    ("catalog watch", []),
    ("catalog reindex", []),
    ("catalog gc", []),
    ("catalog tag", [RUN_NAME, "paper"]),
    ("catalog note", [RUN_NAME, "looks right"]),
    ("catalog query", ["SELECT sim_id FROM simulations"]),
    ("diff", ["diff", RUN_NAME, RUN_NAME]),
    ("config figures", ["config", "figures"]),
    ("data ls", []),
    ("example list", []),
    ("doctor", []),
)


@pytest.mark.parametrize(("verb", "words"), READ_VERBS, ids=[row[0] for row in READ_VERBS])
def test_json_envelope(project: Path, verb: str, words: list[str]) -> None:
    on_the_workspace = verb in ("project list", "site ls", "data ls")
    where = project.parent.parent if on_the_workspace else project
    # A row whose words start with the command names the whole command line itself.
    names_itself = bool(words) and words[0] in ("ls", "show", "diff", "config")
    argv = words if names_itself else [*verb.split(), *words]
    result = CliRunner().invoke([*argv, "-w", str(where), "--format", "json"])
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
def test_empty_listing(tmp_path: Path, words: list[str]) -> None:
    (tmp_path / "projects").mkdir()
    (tmp_path / "data").mkdir()
    verb = " ".join(words)

    as_json = CliRunner().invoke([*words, "-w", str(tmp_path), "--format", "json"])
    as_csv = CliRunner().invoke([*words, "-w", str(tmp_path), "--format", "csv"])

    assert as_json.exit_code == 0, as_json.stderr
    assert json.loads(as_json.stdout) == {"schema": output_of(verb).schema, "data": []}
    assert next(csv.reader(io.StringIO(as_csv.stdout))) == list(output_of(verb).fields)


def test_workspace_flag_position(project: Path) -> None:
    before = CliRunner().invoke(["-w", str(project), "ls", "--format", "json"])
    assert [row["name"] for row in json.loads(before.stdout)["data"]] == [RUN_NAME]

    both = CliRunner().invoke(["-w", "/nowhere", "ls", "-w", str(project), "--format", "json"])
    assert both.exit_code == 0, both.stderr


def test_emit_strict_json(capsys, tmp_path: Path) -> None:
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
def test_plain(value: object, expected: object) -> None:
    assert plain(value) == expected


def test_csv(capsys) -> None:
    args = argparse.Namespace(format="csv")
    emit(args, "project list", [{"name": "a", "run_tomls": ["x.toml", "y.toml"]}])
    assert capsys.readouterr().out.splitlines() == [
        "name,path,has_project_toml,run_tomls",
        "a,,,x.toml;y.toml",
    ]
    emit(args, "project new", {"path": "/p"})
    assert capsys.readouterr().out.splitlines() == ["key,value", "path,/p"]


def test_library_prints_go_to_stderr(capfd) -> None:
    args = argparse.Namespace(format="json")

    with stdout_for_a_program(args):
        print("a library that prints")
        os.write(1, b"a solver that prints\n")
        emit(args, "project new", {"path": "/p"})

    captured = capfd.readouterr()
    assert json.loads(captured.out)["data"] == {"path": "/p"}
    assert "a library that prints" in captured.err and "a solver that prints" in captured.err


def test_failure_code_and_envelope(tmp_path: Path) -> None:
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


def test_no_error_after_a_result(project: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    assert CliRunner().invoke(["publish", RUN_NAME, "--to", str(copy), "-w", str(project)]).ok
    (copy / "added.txt").write_text("not in PUBLICATION.json", encoding="utf-8")

    result = CliRunner().invoke(["publish", "--verify", str(copy), "--format", "json"])

    assert result.exit_code == EXIT_GENERIC
    document = json.loads(result.stdout)
    assert document["schema"] == "hmp.publish.verify.v1"
    assert any("added.txt" in line for line in document["data"]["problems"])


def test_dry_run_document(tmp_path: Path) -> None:
    file = tmp_path / "run.toml"
    file.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    result = CliRunner().invoke(["run", str(file), "--dry-run", "--format", "json"])

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)["data"]
    assert data["workflow"] == "simulation" and data["dry_run"] is True
    assert data["result"]["steps"]


def test_usage_error_code() -> None:
    result = CliRunner().invoke(["ls", "--format", "yaml"])
    assert result.exit_code == EXIT_USAGE
    assert "HMPY.E001: " in result.stderr and "invalid choice" in result.stderr


def test_interruption(capsys) -> None:
    with pytest.raises(SystemExit) as stopped:
        fail(KeyboardInterrupt())
    assert stopped.value.code == 130
    assert capsys.readouterr().err == "Interrupted.\n"


def test_error_code_of_a_step() -> None:
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
    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    monkeypatch.setattr("hydromodpy.project.api.calibrate", lambda *a, **k: report)
    return CliRunner().invoke(["calibrate", str(config), "--format", "json", *flags])


def test_calibrate_payload(monkeypatch, tmp_path: Path) -> None:
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


def test_calibrate_payload_from_disk(monkeypatch, tmp_path: Path) -> None:
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


def test_unfinished_session(monkeypatch, tmp_path: Path) -> None:
    report = _report(extra={"promotion_failures": ["trial 1: no space left"]})

    result = _calibrate(monkeypatch, tmp_path, report)

    assert result.exit_code == EXIT_CALIBRATION
    assert json.loads(result.stdout)["schema"] == "hmp.calibrate.v1"
    assert "trial 1: no space left" in result.stderr


def test_preview_and_apply(project: Path) -> None:
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


def test_removal_without_y(project: Path) -> None:
    result = CliRunner().invoke(["catalog", "trash", "--empty", "-w", str(project)])
    assert result.exit_code == EXIT_USAGE
    assert "-y" in result.stderr


def _checked(mismatches: list, *, diverged: bool = False) -> dict:
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "schema_diverged": diverged,
        "locked_schema": "a" * 64,
        "current_schema": "b" * 64 if diverged else "a" * 64,
    }


MISMATCH = SimpleNamespace(kind="missing", variable="dem", source="ign", station_id=None, path="x")


@pytest.mark.parametrize(
    ("result", "flags", "code", "said"),
    [
        (_checked([MISMATCH]), [], EXIT_VALIDATION, "[missing] dem/ign/None -> x"),
        (_checked([MISMATCH]), ["--strict"], EXIT_VALIDATION, "ERROR: 1 mismatch(es)"),
        (_checked([]), [], 0, "OK: the data cache matches the lockfile"),
        (_checked([], diverged=True), [], 0, "OK"),
        (_checked([], diverged=True), ["--strict"], EXIT_VALIDATION, "OK"),
    ],
    ids=["mismatch", "mismatch strict", "match", "schema changed", "schema changed strict"],
)
def test_data_lock_check(monkeypatch, result: dict, flags: list[str], code: int, said: str) -> None:
    calls: dict[str, object] = {}

    def fake_verify(workspace, *, project, lockfile, strict):
        calls.update({"project": project, "lockfile": lockfile, "strict": strict})
        return result

    monkeypatch.setattr("hydromodpy.project.data_cache.verify_data_lock", fake_verify)

    table = CliRunner().invoke(["data", "lock", "--check", *flags])

    assert table.exit_code == code, table.stderr
    assert said in table.stdout
    assert calls["strict"] is bool(flags)


def test_data_lock_check_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.project.data_cache.verify_data_lock", lambda *a, **k: _checked([])
    )

    out = CliRunner().invoke(["data", "lock", "--check", "--format", "json"])

    document = json.loads(out.stdout)
    assert document["schema"] == output_of("data lock check").schema
    assert set(document["data"]) == set(output_of("data lock check").fields)


@pytest.mark.parametrize(
    ("flags", "said"),
    [(["--strict"], "--strict goes with --check"), (["--lockfile", "x"], "--lockfile goes with")],
)
def test_data_lock_check_options(flags: list[str], said: str) -> None:
    result = CliRunner().invoke(["data", "lock", *flags])
    assert result.exit_code == EXIT_USAGE
    assert said in result.stderr


def test_data_lock_check_destination() -> None:
    result = CliRunner().invoke(["data", "lock", "--check", "--to", "x.lock"])
    assert result.exit_code == EXIT_USAGE
    assert "--lockfile" in result.stderr


def test_data_lock_writes(monkeypatch) -> None:
    written = DataLock(
        path=Path("hydromodpy.lock"),
        inputs=3,
        user_files=1,
        refused_configs=((Path("configs/bad.toml"), "no [workflow]"),),
    )
    monkeypatch.setattr("hydromodpy.project.data_cache.lock_data", lambda *a, **k: written)

    table = CliRunner().invoke(["data", "lock"])
    as_json = CliRunner().invoke(["data", "lock", "--format", "json"])

    assert table.exit_code == 0, table.stderr
    assert "3 input(s), 1 of them user files" in table.stdout
    assert "configs/bad.toml is not locked" in table.stderr
    data = json.loads(as_json.stdout)["data"]
    assert data["refused_configs"] == [{"path": "configs/bad.toml", "reason": "no [workflow]"}]


def test_check_workspace_names(project: Path) -> None:
    file = project / "run.toml"
    file.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    result = CliRunner().invoke(["check", str(file), "--format", "json"])

    names = [check["name"] for check in json.loads(result.stdout)["data"]["workspace"]]
    assert {"workspace", "catalog_path", "data_dir", "runs_dir"} <= set(names)


def test_check_payload(project: Path) -> None:
    file = project / "run.toml"
    file.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    result = CliRunner().invoke(["check", str(file), "--format", "json"])

    data = json.loads(result.stdout)["data"]
    assert set(data) == {"ok", "diagnostics", "workspace"}
    assert data["ok"] is False
    assert {item["code"] for item in data["diagnostics"]} >= {"to_fill"}
    assert {"pointer", "code", "severity", "phrase", "msg"} <= set(data["diagnostics"][0])


def test_cache_dry_run(tmp_path: Path) -> None:
    (tmp_path / "data" / "dem").mkdir(parents=True)
    (tmp_path / "projects").mkdir()
    served = tmp_path / "data" / "dem" / "dem_ign_a.tif"
    served.write_bytes(b"x")
    CacheIndex(tmp_path / "data").record(served, variable="dem", source="ign")

    for words in (
        ["data", "remove", "--variable", "dem", "--dry-run"],
        ["data", "prune", "--older-than", "0", "--dry-run"],
    ):
        result = CliRunner().invoke([*words, "-w", str(tmp_path), "--format", "json"])
        assert result.exit_code == 0, result.stderr
        data = json.loads(result.stdout)["data"]
        assert data["applied"] is False
        assert data["removed"] == 1

    assert [row.path for row in CacheIndex(tmp_path / "data").rows()] == [served.resolve()]


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
    state = {}
    for path in sorted(root.rglob("*")):
        info = path.stat()
        state[str(path.relative_to(root))] = (
            0 if path.is_dir() else info.st_size,
            info.st_mtime_ns,
        )
    return state


def test_dry_runs_change_nothing(project: Path, tmp_path: Path) -> None:
    workspace = project.parent.parent
    other = tmp_path / "other"
    (other / "data").mkdir(parents=True)
    (other / "projects").mkdir()
    (project / "runs" / RUN_NAME / "config.toml").write_text('[site]\nname = "x"\n', "utf-8")
    old_key = tmp_path / "old.toml"
    old_key.write_text('[modflow6.runtime]\nmf6_ims_complexity = "SIMPLE"\n', encoding="utf-8")
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
    assert "-[modflow6.runtime]" in table.stdout
    assert "+[solver.modflow6.runtime]" in table.stdout


def _replay_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ref": "runs/probe.v2",
        "source": "probe.v2",
        "sim_id": "0123456789abcdef",
        "name": "probe",
        "rel_dir": "runs/probe.v3",
        "class": "bit",
        "basis": "float64",
        "differs": {},
        "added": [],
        "removed": [],
        "changes": [],
        "strict": False,
    }
    payload.update(overrides)
    return payload


def test_replay_fields() -> None:
    assert set(output_of("replay").fields) == set(_replay_payload())


def test_replay_print_reproduced(capsys) -> None:
    from hydromodpy.cli.commands.replay import _print

    _print(_replay_payload())

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "replayed probe.v2 as runs/probe.v3  [01234567]",
        "  values : bit, basis float64",
    ]


def test_replay_print_deviation(capsys) -> None:
    from hydromodpy.cli.commands.replay import _print

    _print(
        _replay_payload(
            **{
                "class": "deviation",
                "differs": {"k.mean": {"moved": True}},
                "added": ["budget.inflow"],
                "removed": ["budget.outflow"],
                "changes": ["changes.toml#E71"],
            }
        )
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == (
        "  values : deviation (1 value(s) moved, 1 added, 1 removed), basis float64"
    )
    assert lines[2] == "  changes: changes.toml#E71"


def test_replay_print_no_comparison(capsys) -> None:
    from hydromodpy.cli.commands.replay import _print

    _print(_replay_payload(**{"class": None, "basis": None}))

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "  values : no comparison, the source keeps none this replay can read"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, ""),
        (3, "3"),
        (2.0, "2.0"),
        (1234.5678, "1234.6"),
        (datetime(2026, 11, 11, 9, 30, 15, 123456), "2026-11-11T09:30:15"),
        ("text", "text"),
    ],
)
def test_table_cell(value: object, text: str) -> None:
    assert table_cell(value) == text


def test_table_columns(capsys) -> None:
    rows = [{"site": "a", "label": "long label", "gauge": None, "x_outlet": 1.25}]

    print_table("site ls", rows, ("site", "label", "gauge", "x_outlet"))

    lines = capsys.readouterr().out.splitlines()
    assert lines == ["site  label       gauge  x_outlet", "a     long label         1.2"]


def test_table_header(capsys) -> None:
    print_table("site ls", [{}])
    header = capsys.readouterr().out.splitlines()[0].split()
    assert tuple(header) == output_of("site ls").fields

    print_table("ls plan", [{"case_id": "c1", "status": "completed"}])
    header = capsys.readouterr().out.splitlines()[0].split()
    assert tuple(header) == output_of("ls plan").row_fields


def test_declared_columns() -> None:
    from hydromodpy.cli.commands.project.log import CSV_COLUMNS

    assert CSV_COLUMNS == tuple(f for f in output_of("project log").fields if f != "log_tail")
    assert output_of("workspace list").fields[:3] == ("project", "name", "site")
    assert "case_id" in output_of("ls plan").row_fields
