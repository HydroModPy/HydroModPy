"""``hydromodpy.lock`` written from the sidecars, read, verified, and frozen on.

The lock is written by ``hmp data lock`` or by the launcher at the end of its
prepare phase, never by a run. Its one address is the project root. Two writes
of the same cache differ only by their timestamps.
"""

from __future__ import annotations

import inspect
import os
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit

from hydromodpy.core.exceptions import DataCacheError, FrozenDataError, SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance import lockfile
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_SCHEMA,
    LockedInput,
    frozen_project_root,
    is_frozen_mode,
    locked_inputs,
    project_lockfile_path,
    read_lockfile_inputs,
    read_lockfile_meta,
    read_lockfile_schema_sha256,
    reject_frozen_record,
    reject_frozen_row,
    set_frozen_mode,
    user_file_input,
    verify_lockfile,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import CacheIndex, empty_path_for


@pytest.fixture
def frozen_mode_reset() -> Iterator[None]:
    """Leave the process-wide frozen mode as it was found."""
    was_enabled = is_frozen_mode()
    bound_root = frozen_project_root()
    yield
    if was_enabled and bound_root is not None:
        set_frozen_mode(True, project_root=bound_root)
    else:
        set_frozen_mode(False)


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


# -- the format ---------------------------------------------------------------


def test_write_lockfile_contains_required_sections(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    dest = data_root.parent / LOCKFILE_NAME
    write_lockfile(dest, data_root, schema_sha256="cafe")

    doc = tomlkit.parse(dest.read_text())
    assert doc["schema"] == LOCKFILE_SCHEMA == "hydromodpy.lock.v2"
    assert set(doc) == {"schema", "hydromodpy", "input"}

    meta = read_lockfile_meta(dest)
    assert {"hydromodpy_version", "python_version", "generated_at"} <= set(meta)
    assert meta["config_schema_sha256"] == "cafe"
    for gone in ("catalog_schema_version", "zarr_schema_version", "parquet_schema_version"):
        assert gone not in meta
    assert set(doc["input"][0]) == {
        "variable",
        "source",
        "station_id",
        "product",
        "path",
        "sha256",
        "bytes",
        "license",
        "fetched_at",
    }


def test_each_input_carries_its_licence(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    dest = data_root.parent / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    (item,) = read_lockfile_inputs(dest)
    assert item.license == "etalab-2.0"
    assert item.product == "QmnJ"


_REFUSED_SHAPES = {
    "the lockfile of 2.0.0": 'schema = "hydromodpy.lock.v1"\n\n[hydromodpy]\nhydromodpy_version = "2.0.0"\n',
    "an older shape without schema": '[hydromodpy]\nversion = "2.0.0"\n\n[schema]\ncatalog = 1\n',
    "a later version": 'schema = "hydromodpy.lock.v3"\n',
}


@pytest.mark.parametrize("text", _REFUSED_SHAPES.values(), ids=_REFUSED_SHAPES.keys())
def test_a_lockfile_of_another_shape_is_refused_by_name(tmp_path: Path, text: str) -> None:
    dest = tmp_path / LOCKFILE_NAME
    dest.write_text(text)

    with pytest.raises(SchemaVersionMismatchError, match="hmp data lock"):
        read_lockfile_inputs(dest)


def test_the_lockfile_of_the_corpus_is_refused(tmp_path: Path) -> None:
    corpus = (
        Path(__file__).resolve().parents[3]
        / "regression"
        / "frozen_documents"
        / "v2.0.0"
        / "current"
        / "island"
        / LOCKFILE_NAME
    )
    copy = tmp_path / LOCKFILE_NAME
    copy.write_bytes(corpus.read_bytes())
    with pytest.raises(SchemaVersionMismatchError, match=r"hydromodpy\.lock\.v1.*hmp data lock"):
        read_lockfile_inputs(copy)


def test_a_lockfile_carries_no_binaries_and_no_path_of_this_machine(tmp_path: Path) -> None:
    # A solver's digest is sealed by each run; the lockfile pins the data.
    data_root, _ = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    assert "binaries" not in tomlkit.parse(dest.read_text())
    assert str(tmp_path) not in dest.read_text()


def test_the_data_layer_holds_no_copy_of_the_schema_digest() -> None:
    """The digest of the config schema is read by project and handed in: no default value."""
    parameters = inspect.signature(write_lockfile).parameters
    assert parameters["schema_sha256"].default is None
    assert not {"zarr_schema_version", "parquet_schema_version", "solvers"} & set(parameters)


def test_the_old_resolver_is_gone() -> None:
    assert not hasattr(lockfile, "workspace_lockfile_path")
    assert not hasattr(lockfile, "read_lockfile_binaries")


def test_lockfile_includes_inputs_sha256(tmp_path: Path) -> None:
    data_root, (src,) = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    (item,) = read_lockfile_inputs(dest)
    assert item.path == "hydrometry/hydrometry_hubeau_A.csv"
    assert item.sha256 == sha256_of(src)
    assert item.bytes == src.stat().st_size


def test_an_empty_answer_is_pinned_without_bytes(tmp_path: Path) -> None:
    """A station that answered nothing is a row, pinned so that ``--frozen`` replays it."""
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


def test_two_grids_of_one_source_are_two_inputs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    folder = data_root / "precipitation"
    folder.mkdir(parents=True)
    index = CacheIndex(data_root)
    for name, body in (("precip_a.nc", "a"), ("precip_b.nc", "b")):
        (folder / name).write_text(body)
        index.record(folder / name, variable="precipitation", source="sim2")
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)

    assert {item.path for item in read_lockfile_inputs(dest)} == {
        "precipitation/precip_a.nc",
        "precipitation/precip_b.nc",
    }
    assert verify_lockfile(data_root, dest) == []


def test_a_user_file_is_pinned_relative_to_its_project(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    project_root = data_root.parent / "projects" / "demo"
    project_root.mkdir(parents=True)
    mine = data_root.parent / "inputs" / "dem.tif"
    mine.parent.mkdir()
    mine.write_bytes(b"dem")
    item = user_file_input(
        mine, variable="dem", project_root=project_root, sha256=sha256_of(mine), license="CC0-1.0"
    )
    dest = project_lockfile_path(project_root)
    write_lockfile(dest, data_root, user_files=[item], project_root=project_root)

    locked = {i.source: i for i in read_lockfile_inputs(dest)}
    assert locked["file"].path == "../../inputs/dem.tif"
    assert locked["file"].license == "CC0-1.0"
    assert verify_lockfile(data_root, dest) == []
    mine.write_bytes(b"other dem")
    (mismatch,) = verify_lockfile(data_root, dest, strict=True)
    assert (mismatch.kind, mismatch.source, mismatch.path) == (
        "sha256",
        "file",
        "../../inputs/dem.tif",
    )


# -- atomic writing ------------------------------------------------------------


def test_write_lockfile_atomic(tmp_path: Path) -> None:
    """A pre-existing lockfile is replaced in one rename, never partly overwritten."""
    data_root, src = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    dest.write_text('[hydromodpy]\nversion = "old"\n', encoding="utf-8")
    before = dest.stat()

    write_lockfile(dest, data_root)

    after = dest.stat()
    assert (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
    assert [p for p in dest.parent.iterdir() if p.name.startswith(f".{dest.name}.tmp.")] == []
    assert tomlkit.parse(dest.read_text())["schema"] == LOCKFILE_SCHEMA
    if os.name == "posix":
        assert dest.stat().st_mode & 0o777 in {0o644, 0o664}


def test_atomic_write_uses_a_short_temporary_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tmp sibling keeps 8 hex chars, the repo-wide budget against MAX_PATH."""
    swapped: list[str] = []
    real_replace = os.replace

    def spy(src: object, dst: object) -> None:
        swapped.append(Path(str(src)).name)
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", spy)
    dest = tmp_path / LOCKFILE_NAME
    lockfile._atomic_write_text(dest, 'version = "1"\n')

    assert dest.read_text() == 'version = "1"\n'
    prefix = f".{LOCKFILE_NAME}.tmp."
    assert len(swapped) == 1
    assert swapped[0].startswith(prefix)
    assert len(swapped[0]) - len(prefix) == 8


# -- determinism ---------------------------------------------------------------

_VOLATILE = re.compile(r'(generated_at\s*=\s*"[^"]*"|fetched_at\s*=\s*"[^"]*")')


def test_two_writes_are_byte_identical_after_timestamp_normalisation(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path, ("A", "B"))
    a, b = tmp_path / "a.lock", tmp_path / "b.lock"
    write_lockfile(a, data_root, schema_sha256="cafef00d")
    write_lockfile(b, data_root, schema_sha256="cafef00d")
    assert _VOLATILE.sub("<ts>", a.read_text()) == _VOLATILE.sub("<ts>", b.read_text())


def test_one_write_stamps_every_entry_with_the_same_instant(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path, ("A", "B"))
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    doc = tomlkit.parse(dest.read_text())
    stamps = {str(entry["fetched_at"]) for entry in doc["input"]}
    stamps.add(str(doc["hydromodpy"]["generated_at"]))
    assert len(stamps) == 1
    assert next(iter(stamps)).endswith("+00:00")


def test_input_ordering_is_stable_across_writes(tmp_path: Path) -> None:
    data_root, files = _seed(tmp_path, ("B", "A"))
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    first = [item.path for item in read_lockfile_inputs(dest)]
    write_lockfile(dest, data_root)
    second = [item.path for item in read_lockfile_inputs(dest)]
    assert first == second == sorted(_key(data_root, path) for path in files)


def test_snapshot_round_trips_to_the_sidecars(tmp_path: Path) -> None:
    data_root, (first, second) = _seed(tmp_path, ("A", "B"))
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    by_path = {entry.path: entry for entry in read_lockfile_inputs(dest)}

    a = by_path[_key(data_root, first)]
    assert isinstance(a, LockedInput)
    assert (a.variable, a.source, a.station_id) == ("hydrometry", "hubeau", "A")
    assert a.sha256 == sha256_of(first)
    assert a.bytes == first.stat().st_size
    assert by_path[_key(data_root, second)].station_id == "B"
    assert a.sha256 != by_path[_key(data_root, second)].sha256
    assert verify_lockfile(data_root, dest) == []


def test_schema_sha256_round_trips_and_may_be_absent(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root, schema_sha256="0123abcd")
    assert read_lockfile_schema_sha256(dest) == "0123abcd"
    no_header = tmp_path / "noheader.lock"
    no_header.write_text(f'schema = "{LOCKFILE_SCHEMA}"\n')
    assert read_lockfile_schema_sha256(no_header) is None


# -- verify --------------------------------------------------------------------


def test_verify_passes_when_unchanged(tmp_path: Path) -> None:
    data_root, _ = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    assert verify_lockfile(data_root, dest) == []
    assert verify_lockfile(data_root, dest, strict=True) == []


@pytest.mark.parametrize("strict", [False, True], ids=["frozen", "strict"])
def test_verify_flags_a_changed_input(tmp_path: Path, strict: bool) -> None:
    data_root, (src,) = _seed(tmp_path)
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    src.write_text("datetime,value\n2020-01-01,9.0\n")

    (mismatch,) = verify_lockfile(data_root, dest, strict=strict)

    assert mismatch.kind == "sha256"
    assert mismatch.path == _key(data_root, src)
    assert mismatch.expected != mismatch.observed


@pytest.mark.parametrize("strict", [False, True], ids=["frozen", "strict"])
def test_verify_flags_a_deleted_input(tmp_path: Path, strict: bool) -> None:
    data_root, (first, _) = _seed(tmp_path, ("A", "B"))
    dest = tmp_path / LOCKFILE_NAME
    write_lockfile(dest, data_root)
    expected = sha256_of(first)
    first.unlink()

    (mismatch,) = verify_lockfile(data_root, dest, strict=strict)

    assert (mismatch.kind, mismatch.expected, mismatch.observed) == ("missing", expected, None)


def test_verify_flags_a_row_recorded_after_the_lock(tmp_path: Path) -> None:
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


def test_strict_answers_without_strict_for_a_lockfile_that_names_nothing(tmp_path: Path) -> None:
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


# -- frozen mode -----------------------------------------------------------------


def test_project_lockfile_path_is_the_project_root(tmp_path: Path) -> None:
    assert project_lockfile_path(tmp_path) == tmp_path / LOCKFILE_NAME


def test_locked_inputs_names_the_expected_path_when_missing(
    tmp_path: Path, frozen_mode_reset: None
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    set_frozen_mode(True, project_root=project_root)

    expected = project_lockfile_path(project_root.resolve())
    with pytest.raises(RuntimeError, match=re.escape(str(expected))):
        locked_inputs()


def test_locked_inputs_without_a_bound_project_says_so(frozen_mode_reset: None) -> None:
    set_frozen_mode(False)
    with pytest.raises(RuntimeError, match="no project bound"):
        locked_inputs()


def test_enabling_frozen_mode_without_a_project_is_refused(frozen_mode_reset: None) -> None:
    with pytest.raises(ValueError, match="project_root"):
        set_frozen_mode(True)
    assert is_frozen_mode() is False


def test_every_enable_names_its_own_project(tmp_path: Path, frozen_mode_reset: None) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    set_frozen_mode(True, project_root=first)
    assert frozen_project_root() == first.resolve()
    set_frozen_mode(True, project_root=second)
    assert frozen_project_root() == second.resolve()
    with pytest.raises(ValueError, match="project_root"):
        set_frozen_mode(True)
    set_frozen_mode(False)
    assert frozen_project_root() is None


@pytest.mark.parametrize(
    ("station", "digest", "refusal"),
    [
        ("A", None, None),
        ("A", "0" * 64, "SHA-256"),
        ("B", None, "absent from hydromodpy.lock"),
    ],
    ids=["pinned", "another digest", "not pinned"],
)
def test_frozen_matching_reads_the_one_record(
    tmp_path: Path, frozen_mode_reset: None, station: str, digest: str | None, refusal: str | None
) -> None:
    """A row and a new record are both matched against ``[[input]]``."""
    data_root, (src,) = _seed(tmp_path)
    project_root = data_root.parent
    write_lockfile(project_lockfile_path(project_root), data_root)
    set_frozen_mode(True, project_root=project_root)
    found = {"variable": "hydrometry", "source": "hubeau", "station_id": station}
    sha256 = digest or sha256_of(src)
    path = _key(data_root, src)

    for check in (reject_frozen_row, reject_frozen_record):
        if refusal is None:
            check(**found, path=path, sha256=sha256)
        else:
            with pytest.raises(FrozenDataError, match=refusal):
                check(**found, path=path, sha256=sha256)


def test_a_frozen_refusal_is_a_typed_data_failure(tmp_path: Path, frozen_mode_reset: None) -> None:
    """A frozen run that meets a refusal exits as a data failure."""
    from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for

    project_root = tmp_path / "project"
    project_root.mkdir()
    set_frozen_mode(True, project_root=project_root)

    with pytest.raises(DataCacheError) as info:
        locked_inputs()

    assert isinstance(info.value, FrozenDataError)
    assert exit_code_for(info.value) == EXIT_VALIDATION


# -- one address: what hmp data lock writes is what --frozen reads ---------------


def test_frozen_mode_reads_the_lockfile_lock_data_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen_mode_reset: None
) -> None:
    from hydromodpy.project.data_cache import lock_data

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, project_root, _ = _seed_workspace_project(tmp_path)
    lock_data(project=str(project_root))

    assert project_lockfile_path(project_root).is_file()
    assert not (workspace / LOCKFILE_NAME).exists()
    assert not (workspace / "data" / LOCKFILE_NAME).exists()
    set_frozen_mode(True, project_root=project_root)
    assert [item.station_id for item in locked_inputs()] == ["A"]


def test_frozen_precheck_accepts_the_lockfile_lock_data_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``hmp run --frozen`` resolves the address ``hmp data lock`` writes."""
    from hydromodpy.cli.commands.run import _verify_frozen_inputs_strict
    from hydromodpy.project.data_cache import lock_data

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    raw_toml = {"workspace": {"project_root": str(project_root)}}
    lock_data(project=str(project_root))

    assert _verify_frozen_inputs_strict(config_path, raw_toml) == project_root


def test_a_named_project_root_beats_the_declared_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The project a command names moves the lockfile ``--frozen`` reads, as it moves the config."""
    from hydromodpy.cli.commands.run import _verify_frozen_inputs_strict
    from hydromodpy.project.data_cache import lock_data

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, declared, config_path = _seed_workspace_project(tmp_path)
    env_root = workspace / "projects" / "under_test"
    env_root.mkdir()
    lock_data(project=str(env_root))
    raw_toml = {"workspace": {"project_root": str(declared)}}

    assert project_lockfile_path(env_root).is_file()
    assert not project_lockfile_path(declared).exists()
    assert (
        _verify_frozen_inputs_strict(config_path, raw_toml, project_root=env_root)
        == env_root.resolve()
    )


def test_the_lockfile_records_the_project_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.project.data_cache import lock_data

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.setattr(lockfile, "_git_head", lambda cwd: f"commit-of-{Path(cwd).name}")
    _, project_root, _ = _seed_workspace_project(tmp_path)

    written = lock_data(project=str(project_root))

    assert written.path == project_lockfile_path(project_root)
    assert read_lockfile_meta(written.path)["project_git_commit"] == "commit-of-demo"


def test_project_runner_binds_the_project_root_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen_mode_reset: None
) -> None:
    """``ProjectRunner.run(frozen=True)`` reaches the lockfile, not a RuntimeError.

    Only the pipeline is replaced: the frozen binding and its restore are the
    real ones from :mod:`hydromodpy.project.runner`.
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
            seen["frozen"] = is_frozen_mode()
            seen["root"] = frozen_project_root()
            seen["stations"] = [a.station_id for a in locked_inputs()]
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
    assert seen["frozen"] is True
    assert seen["root"] == project_root.resolve()
    assert seen["stations"] == ["A"]
    assert is_frozen_mode() is False
    assert frozen_project_root() is None


def test_a_run_writes_no_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``hmp run`` leaves the project lockfile alone; disk is the contract."""
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
    monkeypatch.setitem(
        project_workflow.DISPATCH,
        "overview",
        lambda path, **_: SimpleNamespace(to_dict=lambda: {"sim_id": "stub", "name": "stub"}),
    )
    monkeypatch.chdir(workspace)
    args = argparse.Namespace(
        config=str(config_path), credentials=None, allow_host=None, max_download_bytes=None
    )
    run_cmd.run(args)

    assert not (workspace / LOCKFILE_NAME).exists()
