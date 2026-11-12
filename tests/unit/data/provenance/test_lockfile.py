"""``hydromodpy.lock`` written from the sidecars, read, verified, and frozen on.

The lock is written by ``hmp data lock`` or by the launcher at the end of its
prepare phase, never by a run. Its one address is the project root. Two writes
of the same cache differ only by their timestamps.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import DataCacheError, FrozenDataError, SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance import lockfile
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_SCHEMA,
    LockedInputs,
    project_lockfile_path,
    read_locked_inputs,
    read_lockfile_inputs,
    read_lockfile_meta,
    read_lockfile_schema_sha256,
    reject_frozen_record,
    reject_frozen_row,
    user_file_input,
    verify_lockfile,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import CacheIndex, empty_path_for


def _seed(tmp: Path, stations: tuple[str, ...] = ("A",)) -> tuple[Path, list[Path]]:
    """A data folder with one chronicle per station, recorded from the disk."""
    data_root = tmp / "workspace" / "data"
    folder = data_root / "hydrometry"
    folder.mkdir(parents=True)
    index = CacheIndex(data_root)
    files = []
    for number, station in enumerate(stations):
        path = folder / f"hydrometry_hubeau_{station}.csv"
        path.write_text(f"datetime,value\n2020-01-0{number + 1},{number + 1}.0\n")
        index.record(
            path, variable="hydrometry", source="hubeau", station_id=station, product="QmnJ"
        )
        files.append(path)
    return data_root, files


def _key(data_root: Path, path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def _seed_workspace_project(tmp: Path) -> tuple[Path, Path, Path]:
    """A workspace with one cached chronicle and one project one level down."""
    data_root, _ = _seed(tmp)
    workspace = data_root.parent
    project_root = workspace / "projects" / "demo"
    project_root.mkdir(parents=True)
    config_path = project_root / "project.toml"
    config_path.write_text("# config placeholder\n")
    return workspace, project_root, config_path


def test_schema_digest_has_no_default() -> None:
    parameters = inspect.signature(write_lockfile).parameters
    assert parameters["schema_sha256"].default is None
    assert not {"zarr_schema_version", "parquet_schema_version", "solvers"} & set(parameters)


def test_the_old_resolver_is_gone() -> None:
    assert not hasattr(lockfile, "workspace_lockfile_path")
    assert not hasattr(lockfile, "read_lockfile_binaries")


def test_empty_answer_is_pinned(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    folder = data_root / "hydrometry"
    empty = CacheIndex(data_root).record_empty(
        empty_path_for(folder, "hydrometry_hubeau_Z"),
        variable="hydrometry",
        source="hubeau",
        station_id="Z",
    )
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)

    items = {item.station_id: item for item in read_lockfile_inputs(dest)}
    assert sorted(items) == ["A", "Z"]
    assert items["Z"].empty and items["Z"].sha256 is None and items["Z"].bytes is None
    assert items["Z"].path == "hydrometry/hydrometry_hubeau_Z_empty.csv"
    assert "empty = true" in dest.read_text() and not items["A"].empty
    assert verify_lockfile(data_root, dest) == []
    assert verify_lockfile(data_root, dest, strict=True) == []

    empty.sidecar_path.unlink()
    gone = verify_lockfile(data_root, dest, strict=True)
    assert [(m.kind, m.station_id) for m in gone] == [("missing", "Z")]


def test_schema_digest_round_trip(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root, schema_sha256="0123abcd")
    assert read_lockfile_schema_sha256(dest) == "0123abcd"
    no_header = tmp_path / "noheader.lock"
    no_header.write_text(f'schema = "{LOCKFILE_SCHEMA}"\n')
    assert read_lockfile_schema_sha256(no_header) is None


@pytest.mark.parametrize("strict", [False, True], ids=["frozen", "strict"])
def test_verify_flags_a_deleted_input(tmp_path: Path, strict: bool) -> None:
    data_root, (first, _) = _seed(tmp_path, ("A", "B"))
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    expected = sha256_of(first)
    first.unlink()

    (mismatch,) = verify_lockfile(data_root, dest, strict=strict)

    assert (mismatch.kind, mismatch.expected, mismatch.observed) == ("missing", expected, None)


def test_verify_flags_a_late_row(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path, ("A", "B"))
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    extra = data_root / "hydrometry" / "hydrometry_hubeau_C.csv"
    extra.write_text("datetime,value\n2020-01-03,3.0\n")
    CacheIndex(data_root).record(extra, variable="hydrometry", source="hubeau", station_id="C")

    (mismatch,) = verify_lockfile(data_root, dest)

    assert (mismatch.kind, mismatch.station_id, mismatch.expected) == ("missing", "C", None)
    assert mismatch.path == _key(data_root, extra)
    assert verify_lockfile(data_root, dest, strict=True) == []


def test_strict_on_an_empty_lockfile(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "hydrometry").mkdir(parents=True)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    assert read_lockfile_inputs(dest) == []
    assert verify_lockfile(data_root, dest, strict=True) == []
    late = data_root / "hydrometry" / "late.csv"
    late.write_text("datetime,value\n2020-01-01,1.0\n")
    CacheIndex(data_root).record(late, variable="hydrometry", source="hubeau", station_id="A")

    assert [m.kind for m in verify_lockfile(data_root, dest, strict=True)] == ["missing"]


def test_missing_lockfile_names_its_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    expected = project_lockfile_path(project_root.resolve())
    with pytest.raises(FrozenDataError, match=f"existing lockfile at {expected}"):
        read_locked_inputs(project_root)


def test_old_lockfile_shape_refused(tmp_path: Path) -> None:
    (tmp_path / LOCKFILE_NAME).write_text('schema = "hydromodpy.lock.v1"\n')
    with pytest.raises(SchemaVersionMismatchError):
        read_locked_inputs(tmp_path)


@pytest.mark.parametrize(
    "name",
    [
        "_FROZEN_MODE",
        "_FROZEN_PROJECT_ROOT",
        "set_frozen_mode",
        "is_frozen_mode",
        "frozen_project_root",
        "locked_inputs",
    ],
)
def test_no_frozen_state_in_module(name: str) -> None:
    assert not hasattr(lockfile, name)


@pytest.mark.parametrize(
    ("station", "digest", "refusal"),
    [
        ("A", None, None),
        ("A", "0" * 64, "SHA-256"),
        ("B", None, "absent from hydromodpy.lock"),
    ],
    ids=["pinned", "another digest", "not pinned"],
)
def test_frozen_matching(
    tmp_path: Path, station: str, digest: str | None, refusal: str | None
) -> None:
    data_root, (src,) = _seed(tmp_path)
    project_root = data_root.parent
    write_lockfile(project_lockfile_path(project_root), data_root)
    locked = read_locked_inputs(project_root)
    found = {"variable": "hydrometry", "source": "hubeau", "station_id": station}
    sha256 = digest or sha256_of(src)
    path = _key(data_root, src)

    for check in (reject_frozen_row, reject_frozen_record):
        if refusal is None:
            check(locked, **found, path=path, sha256=sha256)
        else:
            with pytest.raises(FrozenDataError, match=refusal):
                check(locked, **found, path=path, sha256=sha256)
        check(None, **found, path=path, sha256=sha256)


def test_frozen_refusal_exit_code(tmp_path: Path) -> None:
    from hydromodpy.cli.exit_codes import EXIT_VALIDATION, exit_code_for

    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(DataCacheError) as info:
        read_locked_inputs(project_root)

    assert isinstance(info.value, FrozenDataError)
    assert exit_code_for(info.value) == EXIT_VALIDATION


def test_precheck_accepts_written_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.project.data_cache import lock_data, verify_frozen_inputs

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, _config_path = _seed_workspace_project(tmp_path)
    lock_data(project=str(project_root))

    verify_frozen_inputs(project_root, {"project_root": str(project_root)})


def test_named_root_beats_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.project.data_cache import (
        FrozenVerificationError,
        lock_data,
        verify_frozen_inputs,
    )

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, declared, _config_path = _seed_workspace_project(tmp_path)
    env_root = workspace / "projects" / "under_test"
    env_root.mkdir()
    lock_data(project=str(env_root))

    assert project_lockfile_path(env_root).is_file()
    assert not project_lockfile_path(declared).exists()
    verify_frozen_inputs(env_root.resolve(), {"project_root": str(declared)})
    with pytest.raises(FrozenVerificationError, match=r"hydromodpy\.lock not found"):
        verify_frozen_inputs(declared)


def test_lockfile_records_git_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.project.data_cache import lock_data

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.setattr(lockfile, "_git_head", lambda cwd: f"commit-of-{Path(cwd).name}")
    _, project_root, _ = _seed_workspace_project(tmp_path)

    written = lock_data(project=str(project_root))

    assert written.path == project_lockfile_path(project_root)
    assert read_lockfile_meta(written.path)["project_git_commit"] == "commit-of-demo"


def test_runner_hands_lock_to_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ProjectRunner.run(frozen=True)`` reads the lockfile once and puts it on ``setup``.

    Only the pipeline is replaced: the lockfile is read by the real runner from
    :mod:`hydromodpy.project.runner`.
    """
    from hydromodpy.project.data_cache import lock_data
    from hydromodpy.project.runner import ProjectRunner

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    lock_data(project=str(project_root))

    seen: dict[str, object] = {}

    class RecordingPipeline:
        def __init__(self, steps: tuple, *, workspace: Path, run_dir: Path | None) -> None:
            seen["workspace"] = workspace

        def run(self, initial: object, **kwargs: object) -> dict:
            seen["locked"] = ctx.setup.locked_inputs
            return {"ctx": ctx}

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", RecordingPipeline)
    monkeypatch.setattr("hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None)
    monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda project: None)

    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(project_root=project_root),
            geographic=None,
            domain=None,
            flow=None,
            run_id=None,
            slot_request=None,
        ),
        data_plan=SimpleNamespace(types=()),
        raw_toml={},
        store=None,
        sim_id=None,
    )
    unpersisted = SimpleNamespace(
        simulation=SimpleNamespace(
            results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=False))
        ),
        site=None,
    )
    project = SimpleNamespace(
        _ctx=ctx,
        _cfg=unpersisted,
        _config_path=config_path,
        _ensure_model_built=lambda: None,
        _phase="uninitialized",
        _data_loaded=set(),
        _no_display=True,
        _run_counter=0,
        _solver=None,
        _store=None,
        _run_history=[],
        _spatial_support_registry=None,
        _requested_support_ids=None,
        _requested_domain_supports=None,
    )

    assert ProjectRunner(project).run(name="frozen_run", frozen=True) is None
    locked = seen["locked"]
    assert isinstance(locked, LockedInputs)
    assert locked.project_root == project_root.resolve()
    assert [item.station_id for item in locked.inputs] == ["A"]


def test_a_run_writes_no_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from hydromodpy.cli.commands import run as run_cmd
    from hydromodpy.project.dispatch import workflow as project_workflow

    data_root, _ = _seed(tmp_path)
    workspace = data_root.parent
    config_path = workspace / "overview.toml"
    config_path.write_text(
        f'[workflow]\nmode = "overview"\n\n[workspace]\nroot = "{workspace.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        project_workflow,
        "run_overview",
        lambda path, **_: SimpleNamespace(to_dict=lambda: {"sim_id": "stub", "name": "stub"}),
    )
    monkeypatch.chdir(workspace)
    args = argparse.Namespace(
        config=str(config_path), credentials=None, allow_host=None, max_download_bytes=None
    )
    run_cmd.run(args)

    assert not (workspace / LOCKFILE_NAME).exists()


@pytest.mark.parametrize(
    ("pins", "lock_name", "edit", "refusal"),
    [
        ("series+location", "inputs.json", None, None),
        ("series", "inputs.json", None, r"absent from inputs\.json.*LOC\.csv.*hmp run"),
        ("series", LOCKFILE_NAME, None, r"absent from hydromodpy\.lock.*hmp data lock"),
        ("series+location", "inputs.json", "notes.csv", r"absent from inputs\.json.*notes\.csv"),
        ("series+location", "inputs.json", "piezometry_custom_LOC.csv", "does not match"),
    ],
)
def test_frozen_replay_of_a_station_folder(
    tmp_path: Path, pins: str, lock_name: str, edit: str | None, refusal: str | None
) -> None:
    from hydromodpy.data.ingest.custom_points import load_file_points
    from hydromodpy.data.source.file import FileSource
    from hydromodpy.data.source.port import FetchRequest

    folder = tmp_path / "data" / "piezometry"
    folder.mkdir(parents=True)
    (folder / "piezometry_custom_LOC.csv").write_text("id,x,y\nW1,305.0,305.0\n")
    (folder / "piezometry_custom_W1_D.csv").write_text("datetime,value\n2003-01-01,2.0\n")
    (record,) = load_file_points(
        data_dir=folder, variable_name="piezometry", internal_unit="m", default_unit="m"
    )
    named = [record.file_path, *record.location_files]
    assert [path.name for path in named] == [
        "piezometry_custom_W1_D.csv",
        "piezometry_custom_LOC.csv",
    ]
    kept = named if pins == "series+location" else named[:1]
    items = tuple(
        user_file_input(path, variable="piezometry", project_root=tmp_path, sha256=sha256_of(path))
        for path in kept
    )
    locked = LockedInputs(project_root=tmp_path, path=tmp_path / lock_name, inputs=items)
    if edit is not None:
        (folder / edit).write_text("id,x,y\nW1,0.0,0.0\n")
    source = FileSource(path=folder, locked=locked)
    source.section = "piezometry"

    if refusal is None:
        assert len(source.fetch(FetchRequest(out_dir=tmp_path)).files) == 2
    else:
        with pytest.raises(FrozenDataError, match=refusal):
            source.fetch(FetchRequest(out_dir=tmp_path))
