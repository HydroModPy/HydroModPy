"""The request of a run, built from every form, its refusals, and its identity."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from hydromodpy.cli.helpers import EXIT_CONFIG, exit_code_for
from hydromodpy.config.loading import load
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.loading.inputs import ResolvedInputs
from hydromodpy.project.request import (
    REQUEST_SCHEMA,
    RunOutcome,
    RunRequest,
    base_of,
    read_request,
    request_of,
    workflow_of,
    write_request_file,
)
from hydromodpy.results.outcome import Outcome, write_outcome
from hydromodpy.results.publication import PublishedLine
from hydromodpy.results.storage.contract import RUN_REQUEST_FILENAME
from hydromodpy.workflow.solution_key import input_digests, planned_request_id

DOCUMENT: dict[str, Any] = {
    "workflow": {"mode": "simulation"},
    "site": {"name": "site_a"},
    "geographic": {"catchment": {"kind": "dem"}},
    "data": {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}},
    "simulation": {"name": "island"},
}
SYNTHETIC: dict[str, Any] = {
    "workflow": {"mode": "simulation"},
    "geographic": {"source_mode": "synthetic"},
}


def _project(root: Path) -> Path:
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "inputs" / "dem.tif").write_bytes(b"never read")
    (root / "project.toml").write_text("[workspace]\n", encoding="utf-8")
    (root / "island.toml").write_text(tomlkit.dumps(DOCUMENT), encoding="utf-8")
    return root


def _request_file(root: Path, payload: Any, name: str = "island.json") -> Path:
    path = root / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# The four forms, and a request file


@pytest.mark.parametrize(
    ("form", "source"),
    [
        pytest.param("toml", lambda root: root / "island.toml", id="a toml file"),
        pytest.param(
            "json",
            lambda root: _request_file(root, {"schema": REQUEST_SCHEMA, "config": DOCUMENT}),
            id="a request file",
        ),
        pytest.param("json", lambda root: json.dumps(DOCUMENT), id="json text"),
        pytest.param("dict", lambda root: DOCUMENT, id="a dict"),
        pytest.param("object", lambda root: load(root / "island.toml"), id="a configuration"),
    ],
)
def test_every_form_gives_a_request_that_loads_alike(tmp_path: Path, form: str, source) -> None:
    root = _project(tmp_path / "project")
    expected = written_payload(load(root / "island.toml"))

    request = request_of(source(root), base=root)

    assert request.form == form
    assert "project_root" not in request.config.get("workspace", {})
    assert written_payload(load(request.config, root)) == expected


def test_a_request_round_trips_through_its_json(tmp_path: Path) -> None:
    request = request_of(
        DOCUMENT, set={"flow.param.K.field.value": 2e-5}, name="island", force=True
    )
    path = _request_file(tmp_path, request.model_dump(mode="json", by_alias=True))

    assert read_request(path) == request
    assert RunRequest.model_validate(request.model_dump(by_alias=True)) == request
    assert request.model_dump(by_alias=True)["schema"] == REQUEST_SCHEMA


def test_the_json_schema_of_a_request_names_its_schema_as_a_constant() -> None:
    schema = RunRequest.model_json_schema(by_alias=True)

    assert schema["properties"]["schema"]["const"] == REQUEST_SCHEMA
    assert schema["additionalProperties"] is False
    assert "config" in schema["required"]


def test_the_source_is_relative_to_the_base_when_it_lies_under_it(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")

    assert request_of(root / "island.toml", base=root).source == "island.toml"
    assert request_of(root / "island.toml", base=tmp_path / "x").source == (
        (root / "island.toml").resolve().as_posix()
    )
    assert request_of(DOCUMENT).source is None


@pytest.mark.parametrize(
    ("options", "no_display"),
    [
        pytest.param({}, False, id="neither"),
        pytest.param({"headless": True}, True, id="headless"),
        pytest.param({"no_display": True}, True, id="no_display"),
    ],
)
def test_headless_is_no_display(options: dict, no_display: bool) -> None:
    assert request_of(DOCUMENT, **options).no_display is no_display


def test_the_command_line_adds_to_a_request_file_and_wins(tmp_path: Path) -> None:
    path = _request_file(
        tmp_path,
        {
            "schema": REQUEST_SCHEMA,
            "config": DOCUMENT,
            "set": {"a.b": 1, "a.c": 1},
            "name": "from_file",
        },
    )

    request = request_of(path, set={"a.c": 2}, name="from_line", fresh=True)

    assert request.set == {"a.b": 1, "a.c": 2}
    assert (request.name, request.fresh, request.form) == ("from_line", True, "json")


def test_the_overrides_name_the_new_keys_and_the_overlays(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    (root / "over.toml").write_text('[simulation]\nname = "over"\n', encoding="utf-8")

    request = request_of(
        root / "island.toml",
        overlays=[root / "over.toml"],
        set={"modflow6.process_specific.vka": 3.0},
    )

    assert request.config["simulation"]["name"] == "over"
    assert request.overrides() == {
        "solver.modflow6.process_specific.vka": 3.0,
        "overlay": ["over.toml"],
    }


@pytest.mark.parametrize(
    ("document", "changes", "workflow"),
    [
        pytest.param({}, {}, "simulation", id="nothing written"),
        pytest.param({"calibration": {}}, {}, "calibration", id="a calibration section"),
        pytest.param(
            {"calibration": {}}, {"workflow.mode": "simulation"}, "simulation", id="a set mode"
        ),
        pytest.param({"overview": {}}, {}, "overview", id="an overview"),
    ],
)
def test_the_workflow_follows_the_document_and_its_changes(
    document: dict, changes: dict, workflow: str
) -> None:
    assert workflow_of(RunRequest(config=document, set=changes)) == workflow


@pytest.mark.parametrize(
    ("form", "written"), [("json", True), ("dict", True), ("toml", False), ("object", False)]
)
def test_request_json_is_written_for_json_and_dict_only(
    tmp_path: Path, form: str, written: bool
) -> None:
    request = RunRequest(config={"a": {"b": "secret value"}}, form=form)

    write_request_file(tmp_path, request)

    path = tmp_path / RUN_REQUEST_FILENAME
    assert path.is_file() is written
    if written:
        assert RunRequest.model_validate_json(path.read_text(encoding="utf-8")) == request


@pytest.mark.parametrize(
    ("source", "base", "expected"),
    [
        pytest.param("toml", None, "project", id="a toml file reads from its project"),
        pytest.param("json", None, "project", id="a request file reads from its project"),
        pytest.param("dict", "other", "other", id="a dict reads from the base given"),
        pytest.param("toml", "other", "other", id="a base given wins"),
        pytest.param("object", None, "project", id="an object reads from its root"),
    ],
)
def test_the_base_of_each_form(
    tmp_path: Path, source: str, base: str | None, expected: str
) -> None:
    root = _project(tmp_path / "project")
    (root / "configs").mkdir()
    given = {
        "toml": root / "island.toml",
        "json": _request_file(root / "configs", {"schema": REQUEST_SCHEMA, "config": {}}),
        "dict": DOCUMENT,
        "object": load(root / "island.toml"),
    }[source]
    folders = {"project": root.resolve(), "other": (tmp_path / "other").resolve()}

    assert base_of(given, None if base is None else folders[base]) == folders[expected]


def test_a_document_in_memory_has_no_base_of_its_own() -> None:
    with pytest.raises(ConfigError, match="needs base="):
        base_of(DOCUMENT)


# The outcome of a finished run, read back


def _finished(run_dir: Path, **fields: Any) -> None:
    run_dir.mkdir(parents=True)
    when = datetime(2026, 11, 9, tzinfo=UTC)
    write_outcome(
        run_dir,
        Outcome(
            case_id=run_dir.name,
            attempt=1,
            attempt_id="a" * 32,
            sim_id="s" * 32,
            status="failed",
            written_by="worker",
            started_at=when,
            ended_at=when,
            host="here",
            pid=1,
            **fields,
        ),
    )


@pytest.mark.parametrize(
    ("identical_to", "request_id"),
    [
        pytest.param(None, "r" * 64, id="a run that computed"),
        pytest.param("island", None, id="a run given back by a skip"),
    ],
)
def test_the_outcome_of_a_run_reads_typed(
    tmp_path: Path, identical_to: str | None, request_id: str | None
) -> None:
    run_dir = tmp_path / "runs" / "island"
    _finished(run_dir, request_id=request_id)

    read = RunOutcome.read(run_dir, project_root=tmp_path, identical_to=identical_to)

    assert (read.name, read.sim_id, read.request_id, read.status) == (
        "island",
        "s" * 32,
        request_id,
        "failed",
    )
    assert read.identical_to == identical_to
    assert read.project_root == tmp_path


def test_the_outcome_of_a_run_carries_the_delivery_lines_it_wrote(tmp_path: Path) -> None:
    """``read`` tells them nothing: a delivery is a line of the run, not of its outcome."""
    run_dir = tmp_path / "runs" / "island"
    _finished(run_dir, request_id="r" * 64)

    fresh = RunOutcome.read(run_dir, project_root=tmp_path)
    line = PublishedLine(
        kind="delivery",
        published_at=datetime(2026, 11, 10, tzinfo=UTC),
        file="exports/head_last.tif",
        destination="ftp://example.org/incoming/head_last.tif",
        state="delivered",
        sha256=hashlib.sha256(b"head").hexdigest(),
        bytes=4,
        attempts=1,
    )
    delivered = RunOutcome(
        name=fresh.name,
        run_dir=fresh.run_dir,
        sim_id=fresh.sim_id,
        request_id=fresh.request_id,
        status=fresh.status,
        identical_to=fresh.identical_to,
        project_root=fresh.project_root,
        deliveries=(line,),
    )

    assert fresh.deliveries == ()
    assert delivered.deliveries == (line,)


def test_a_directory_without_outcome_is_no_finished_run(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        RunOutcome.read(tmp_path, project_root=tmp_path)


# The identity of a request, told by hydromodpy.workflow.solution_key


def test_a_resolved_input_enters_by_its_role_and_another_file_by_its_path(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    cfg = load(root / "island.toml")
    dem = root / "inputs" / "dem.tif"
    digest = hashlib.sha256(dem.read_bytes()).hexdigest()
    record = FileRecord(dem, digest, state="raw", origin="file")

    assert input_digests(cfg, ResolvedInputs(dem=record)) == {"dem.0": [digest, "raw"]}
    (unresolved,) = input_digests(cfg, ResolvedInputs()).items()
    assert unresolved[0].endswith(":inputs/dem.tif")
    assert unresolved[1] == [digest, None]


def test_a_planned_request_id_is_computed_offline(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    remote = {
        **SYNTHETIC,
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem"}},
        "data": {"dem": {"sources": [{"source": "url", "url": "https://example.org/dem.tif"}]}},
    }

    known = planned_request_id(load(SYNTHETIC, root), data_dir=root / "data")
    unknown = planned_request_id(load(remote, root), data_dir=root / "data")

    assert known is not None and len(known) == 64
    assert unknown is None


# Every refusal of a request, with its type, its exit code and a fragment of its sentence


def _rows(root: Path) -> dict[str, Any]:
    bare = _request_file(root, DOCUMENT, "bare.json")
    other = _request_file(root, {"schema": "hydromodpy.request.v9", "config": {}}, "v9.json")
    extra = _request_file(root, {"schema": REQUEST_SCHEMA, "config": {}, "basis": "."}, "x.json")
    chained = _request_file(
        root, {"schema": REQUEST_SCHEMA, "config": {"base_config": "a.toml"}}, "c.json"
    )
    garbled = root / "garbled.json"
    garbled.write_text("{not json", encoding="utf-8")
    listed = _request_file(root, [1, 2], "list.json")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    (root / "script.py").write_text("x = 1\n", encoding="utf-8")
    (root / "over.toml").write_text("", encoding="utf-8")
    calibration = {"calibration": {}}
    overview = {"overview": {}}
    return {
        "a request file without schema": lambda: request_of(bare),
        "a request file of another schema": lambda: request_of(other),
        "a request file with an unknown member": lambda: request_of(extra),
        "base_config in a request file": lambda: request_of(chained),
        "base_config in a dict": lambda: request_of({"base_config": "a.toml"}),
        "a request file that does not parse": lambda: request_of(garbled),
        "a request file that is no object": lambda: request_of(listed),
        "an overlay of a request file": lambda: request_of(
            _request_file(root, {"schema": REQUEST_SCHEMA, "config": {}}, "ok.json"),
            overlays=[root / "over.toml"],
        ),
        "an overlay of a dict": lambda: request_of({}, overlays=[root / "over.toml"]),
        "a python script": lambda: request_of(root / "script.py"),
        "an unknown suffix": lambda: request_of(root / "notes.txt"),
        "a refused run name": lambda: request_of({}, name="Island Run"),
        "a reserved run name": lambda: request_of({}, name="aux"),
        "--resume of an overview": lambda: request_of(overview, resume="x"),
        "--resume REF of a calibration": lambda: request_of(calibration, resume="x"),
        "--until of a calibration": lambda: request_of(calibration, until_step="load_data"),
        "--from of an overview": lambda: request_of(overview, from_step="setup"),
        "--force of an overview": lambda: request_of(overview, force=True),
    }


REFUSALS: list[tuple[str, type[BaseException], str]] = [
    ("a request file without schema", ConfigError, "put the configuration document under config"),
    ("a request file of another schema", ConfigError, "is not a run request this version reads"),
    ("a request file with an unknown member", ConfigValidationError, "basis is not a member"),
    ("base_config in a request file", ConfigError, "base_config is a key of a TOML file"),
    ("base_config in a dict", ConfigError, "base_config is a key of a TOML file"),
    ("a request file that does not parse", ConfigError, "is not valid JSON"),
    ("a request file that is no object", ConfigValidationError, "table of sections"),
    ("an overlay of a request file", ConfigError, "--overlay merges a TOML file"),
    ("an overlay of a dict", ConfigError, "--overlay merges a TOML file"),
    ("a python script", ConfigError, "Python scripts are not supported by 'hmp run'"),
    ("an unknown suffix", ConfigError, "Unsupported file type: .txt (expected .toml or .json)"),
    ("a refused run name", ConfigValidationError, "Write 'island_run'"),
    ("a reserved run name", ConfigValidationError, "Windows reserves"),
    ("--resume of an overview", ConfigError, "--resume is only supported for the 'simulation'"),
    (
        "--resume REF of a calibration",
        ConfigError,
        "pass a bare --resume, not --resume x",
    ),
    ("--until of a calibration", ConfigError, "--set workflow.mode=simulation"),
    ("--from of an overview", ConfigError, "(detected 'overview')"),
    ("--force of an overview", ConfigError, "the two that give back identical completed work"),
]


@pytest.mark.parametrize(("row", "kind", "said"), REFUSALS, ids=[row[0] for row in REFUSALS])
def test_a_refused_request_says_why(
    tmp_path: Path, row: str, kind: type[BaseException], said: str
) -> None:
    with pytest.raises(kind) as refused:
        _rows(tmp_path)[row]()

    assert said in str(refused.value)
    assert exit_code_for(refused.value) == EXIT_CONFIG


@pytest.mark.parametrize("document", [{}, {"calibration": {}}], ids=["simulation", "calibration"])
def test_force_is_taken_by_the_workflows_that_give_back_identical_work(document: dict) -> None:
    """A simulation gives back an identical run and a calibration its completed session."""
    assert request_of(document, force=True).force is True


def test_a_dry_run_is_never_refused_on_its_options() -> None:
    assert request_of({"calibration": {}}, force=True, dry_run=True).dry_run
