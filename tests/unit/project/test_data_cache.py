"""The data cache seen from a project: the lockfile it writes and what a prune keeps."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.config.user_files import user_file_inputs
from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.data.provenance.lockfile import project_lockfile_path, read_lockfile_inputs
from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    empty_path_for,
    load_sidecar,
    write_sidecar,
)
from hydromodpy.project.data_cache import (
    FrozenVerificationError,
    _targets,
    cited_input_digests,
    data_root_for,
    lock_data,
    pinned_empty_paths,
    prune_data,
    verify_data_lock,
    verify_frozen_inputs,
)
from hydromodpy.results.record.manifest import InputEntry
from hydromodpy.results.record.record import InputsDocument


@pytest.fixture(autouse=True)
def _no_workspace_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)


def _fetched(data_root: Path, name: str, body: str) -> Path:
    path = data_root / "hydrometry" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    CacheIndex(data_root).record(
        path, variable="hydrometry", source="hubeau", station_id=name.split(".")[0]
    )
    return path


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.toml").write_text("# placeholder\n")
    return root


def _sealed(run_dir: Path, *digests: str | None) -> Path:
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}")
    document = InputsDocument(
        sim_id=run_dir.name,
        inputs=[
            InputEntry(variable="hydrometry", provider="hubeau", path="x", sha256=digest)
            for digest in digests
        ],
    )
    (run_dir / "inputs.json").write_text(
        json.dumps(document.model_dump(mode="json", by_alias=True))
    )
    return run_dir


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    project = _project(workspace / "projects" / "demo")
    return workspace, project


# -- where the data folder is ------------------------------------------------------


def test_a_project_in_a_workspace_reads_the_workspace_data(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    assert data_root_for(project) == (workspace / "data").resolve()


def test_a_project_without_a_workspace_keeps_its_own_data(tmp_path: Path) -> None:
    alone = _project(tmp_path / "alone")
    assert data_root_for(alone) == alone.resolve() / "data"


# -- the digests a prune keeps -------------------------------------------------------


def test_the_digests_of_every_project_run_trial_and_lockfile_are_cited(tmp_path: Path) -> None:
    workspace, demo = _workspace(tmp_path)
    other = _project(workspace / "projects" / "other")
    _sealed(demo / "runs" / "first", "a" * 64, None)
    _sealed(demo / "sessions" / "calage" / "trials" / "trial-1", "b" * 64)
    _sealed(other / "runs" / "second", "c" * 64)
    kept = _fetched(workspace / "data", "K.csv", "kept")
    lock_data(project=str(other))

    cited = cited_input_digests(workspace)

    assert cited == {"a" * 64, "b" * 64, "c" * 64, sha256_of(kept)}


def test_a_project_that_is_its_own_workspace_cites_its_runs(tmp_path: Path) -> None:
    alone = _project(tmp_path / "alone")
    _sealed(alone / "runs" / "r", "d" * 64)
    assert cited_input_digests(alone) == {"d" * 64}


def test_an_unsealed_run_cites_nothing(tmp_path: Path) -> None:
    workspace, demo = _workspace(tmp_path)
    (demo / "runs" / "draft").mkdir(parents=True)
    assert cited_input_digests(workspace) == frozenset()


_UNREADABLE = {
    "inputs of a run": ("run", "The inputs of the run"),
    "a lockfile of a pre-release of 2.0": ("lockfile", "hmp data lock"),
}


@pytest.mark.parametrize(("what", "said"), _UNREADABLE.values(), ids=_UNREADABLE.keys())
def test_what_cannot_be_read_refuses_the_prune(tmp_path: Path, what: str, said: str) -> None:
    workspace, demo = _workspace(tmp_path)
    fetched = _fetched(workspace / "data", "U.csv", "uncited")
    if what == "run":
        run = demo / "runs" / "broken"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text("{}")
        (run / "inputs.json").write_text("{not json")
    else:
        project_lockfile_path(demo).write_text('schema = "hydromodpy.lock.v1"\n')

    with pytest.raises(DataCacheError, match=said):
        prune_data(workspace, delete_files=True)
    assert fetched.exists()


def test_prune_keeps_the_cited_file_and_removes_the_other(tmp_path: Path) -> None:
    workspace, demo = _workspace(tmp_path)
    cited = _fetched(workspace / "data", "C.csv", "cited")
    other = _fetched(workspace / "data", "O.csv", "other")
    _sealed(demo / "runs" / "r", sha256_of(cited))

    report = prune_data(workspace, older_than_days=0, delete_files=True)

    assert report.kept_cited == (cited,)
    assert report.removed == (other,)
    assert cited.exists() and not other.exists()


def test_prune_keeps_an_old_cited_file_names_it_and_spares_the_young_rows(
    tmp_path: Path,
) -> None:
    workspace, demo = _workspace(tmp_path)
    data = workspace / "data"
    cited = _fetched(data, "C.csv", "cited")
    stale = _fetched(data, "S.csv", "stale")
    young = _fetched(data, "Y.csv", "young")
    for path in (cited, stale):
        sidecar = load_sidecar(path)
        write_sidecar(path, sidecar.model_copy(update={"fetched_at": datetime(2020, 1, 1)}))
    _sealed(demo / "runs" / "r", sha256_of(cited))

    report = prune_data(workspace, older_than_days=365, delete_files=True)

    assert report.kept_cited == (cited,)
    assert report.removed == (stale,)
    assert cited.exists() and young.exists() and not stale.exists()


def _empty_answer(data_root: Path, station: str, *, days_old: float) -> Path:
    """Record a station that answered nothing, fetched *days_old* days ago."""
    index = CacheIndex(data_root)
    path = empty_path_for(data_root / "hydrometry", f"hydrometry_hubeau_{station}")
    path.parent.mkdir(parents=True, exist_ok=True)
    index.record_empty(path, variable="hydrometry", source="hubeau", station_id=station)
    sidecar = load_sidecar(path)
    fetched = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_old)
    write_sidecar(path, sidecar.model_copy(update={"fetched_at": fetched}))
    return path


def test_prune_keeps_an_old_empty_answer_a_lockfile_pins(tmp_path: Path) -> None:
    """An empty answer has no digest, so the lockfile pins it by its path."""
    workspace, demo = _workspace(tmp_path)
    data = workspace / "data"
    pinned = _empty_answer(data, "P", days_old=90)
    lock_data(project=str(demo))
    unpinned = _empty_answer(data, "U", days_old=90)

    assert pinned_empty_paths(workspace) == {"hydrometry/hydrometry_hubeau_P_empty.csv"}
    report = prune_data(workspace, older_than_days=30, delete_files=True)

    assert report.kept_cited == (pinned,)
    assert report.removed == (unpinned,)
    assert [row.path for row in CacheIndex(data).rows()] == [pinned]


def test_a_dry_prune_removes_nothing(tmp_path: Path) -> None:
    workspace, _demo = _workspace(tmp_path)
    data = workspace / "data"
    files = [_fetched(data, f"{name}.csv", name) for name in ("A", "B")]
    before = sorted(path.name for path in data.rglob("*"))

    report = prune_data(workspace, older_than_days=0, delete_files=True, dry_run=True)

    assert report.dry_run and sorted(report.removed) == sorted(files)
    assert sorted(path.name for path in data.rglob("*")) == before


# -- user files of the configurations ------------------------------------------------


def _config_reading(path: Path) -> SimpleNamespace:
    source = SimpleNamespace(source="file", path=path, license="CC0-1.0")
    return SimpleNamespace(
        data=SimpleNamespace(
            types=["dem", "recharge"],
            dem=SimpleNamespace(sources=[source]),
            recharge=SimpleNamespace(sources=[SimpleNamespace(source="sim2", path=None)]),
        )
    )


def test_each_declared_user_file_is_listed_and_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, demo = _workspace(tmp_path)
    folder = demo / "inputs" / "dem"
    folder.mkdir(parents=True)
    (folder / "a.tif").write_bytes(b"a")
    (folder / "b.tif").write_bytes(b"b")
    (folder / ".hidden").write_bytes(b"h")
    configs = demo / "configs"
    configs.mkdir()
    (configs / "broken.toml").write_text("[[[")

    def load(path: Path):
        if path.name == "broken.toml":
            raise ValueError("does not parse")
        return _config_reading(folder)

    monkeypatch.setattr("hydromodpy.config.loading.load", load)

    records, refused = user_file_inputs(demo)

    assert sorted(r.path for r in records) == ["inputs/dem/a.tif", "inputs/dem/b.tif"]
    assert {r.source for r in records} == {"file"}
    assert {r.license for r in records} == {"CC0-1.0"}
    assert records[0].sha256 == sha256_of(demo / records[0].path)
    assert [(p.name, why) for p, why in refused] == [("broken.toml", "does not parse")]


def test_lock_data_pins_the_cache_and_the_user_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, demo = _workspace(tmp_path)
    _fetched(workspace / "data", "A.csv", "a")
    mine = demo / "inputs" / "dem.tif"
    mine.parent.mkdir()
    mine.write_bytes(b"dem")
    monkeypatch.setattr("hydromodpy.config.loading.load", lambda path: _config_reading(mine))

    written = lock_data(project=str(demo))

    assert written.path == project_lockfile_path(demo)
    assert (written.inputs, written.user_files, written.refused_configs) == (2, 1, ())
    assert {i.source for i in read_lockfile_inputs(written.path)} == {"hubeau", "file"}
    assert verify_data_lock(project=str(demo), strict=True)["ok"] is True
    mine.write_bytes(b"another dem")
    assert verify_data_lock(project=str(demo), strict=True)["ok"] is False


def test_a_config_that_does_not_load_is_named_and_others_are_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, demo = _workspace(tmp_path)
    _fetched(workspace / "data", "A.csv", "a")
    written = lock_data(project=str(demo))
    assert [path.name for path, _ in written.refused_configs] == ["project.toml"]
    assert written.inputs == 1


def test_the_cases_of_the_current_plan_of_a_sites_project_lock_their_user_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``[sites]`` project.toml is not loaded alone; the cases of its plan stand for it."""
    import pandas as pd

    from hydromodpy.results.plan_store import Plan, PlanCase, write_plan

    _workspace_root, demo = _workspace(tmp_path)
    (demo / "project.toml").write_text('[sites]\ntable = "sites.csv"\n')
    mine = demo / "inputs" / "dem" / "a.tif"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"a")
    tomls = {"S1-base": 'user = "a.tif"\n', "S2-base": "user = false\n"}
    plan = Plan(
        plan_hash="a3f9c2e1",
        hydromodpy_version="2.1.0",
        created_at=datetime(2026, 11, 9, tzinfo=UTC),
        n_cases=2,
    )
    cases = [
        PlanCase(
            case_id=case_id,
            site=case_id.split("-")[0],
            recipe="base",
            config_hash=f"h{n}",
            config_path=f"{case_id}.toml",
        )
        for n, case_id in enumerate(tomls)
    ]
    write_plan(demo, plan, pd.DataFrame({"site": ["S1", "S2"]}, dtype=str), cases, tomls)
    seen: list[tuple[object, object]] = []

    def load(source, base=None, **_):
        seen.append((source, base))
        if isinstance(source, Path):
            raise AssertionError("a [sites] project.toml is never loaded alone")
        if source["user"]:
            return _config_reading(mine.parent)
        return SimpleNamespace(data=None)

    monkeypatch.setattr("hydromodpy.config.loading.load", load)

    records, refused = user_file_inputs(demo)

    assert [(r.variable, r.path) for r in records] == [("dem", "inputs/dem/a.tif")]
    assert refused == []
    assert [base for _source, base in seen] == [demo.resolve(), demo.resolve()]


# -- the addresses of lock and check ----------------------------------------------


def test_check_accepts_an_explicit_lockfile_from_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--lockfile`` plus ``-w`` names both addresses, so no project is needed."""
    workspace, demo = _workspace(tmp_path)
    _fetched(workspace / "data", "A.csv", "a")
    written = lock_data(project=str(demo)).path

    monkeypatch.chdir(tmp_path)
    assert verify_data_lock(str(workspace), lockfile=str(written))["ok"] is True
    with pytest.raises(FileNotFoundError, match="project.toml"):
        verify_data_lock(str(workspace))


def test_lock_and_check_need_no_project_when_the_file_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The named file is the address and its folder is the project it describes."""
    workspace, _ = _workspace(tmp_path)
    _fetched(workspace / "data", "A.csv", "a")
    restored = workspace / "restored"
    restored.mkdir()
    monkeypatch.chdir(tmp_path)

    written = lock_data(output=str(restored / "custom.lock")).path

    assert written == (restored / "custom.lock").resolve()
    assert verify_data_lock(lockfile=str(written))["ok"] is True


def test_lock_outside_any_workspace_and_without_files_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verb raises; turning that into an exit code is the command's job."""
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    monkeypatch.chdir(orphan)

    with pytest.raises(FileNotFoundError, match="-w"):
        lock_data(output=str(orphan / "custom.lock"))


def test_an_explicit_project_wins_over_the_lockfile_folder(tmp_path: Path) -> None:
    workspace, demo = _workspace(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = elsewhere / "custom.lock"

    _, dest, named = _targets(str(workspace), str(demo), str(out))
    assert dest == out.resolve()
    assert named == demo.resolve()
    _, _, unnamed = _targets(str(workspace), None, str(out))
    assert unnamed == elsewhere.resolve()


def test_check_says_when_the_config_schema_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, demo = _workspace(tmp_path)
    _fetched(workspace / "data", "A.csv", "a")
    lock_data(project=str(demo))
    assert verify_data_lock(project=str(demo))["schema_diverged"] is False

    monkeypatch.setattr(
        "hydromodpy.schema.config_schema.schema_sha256", lambda model: "another schema"
    )
    found = verify_data_lock(project=str(demo))

    assert found["schema_diverged"] is True
    assert found["current_schema"] == "another schema"


def test_a_frozen_run_needs_the_lockfile_and_names_the_way_to_write_it(tmp_path: Path) -> None:
    _workspace_root, demo = _workspace(tmp_path)

    with pytest.raises(FrozenVerificationError, match="hmp data lock"):
        verify_frozen_inputs(demo)


def test_a_frozen_run_reads_the_lockfile_it_is_given_and_names_the_first_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, demo = _workspace(tmp_path)
    _fetched(workspace / "data", "A.csv", "a")
    mine = demo / "inputs" / "dem.tif"
    mine.parent.mkdir()
    mine.write_bytes(b"dem")
    monkeypatch.setattr("hydromodpy.config.loading.load", lambda path: _config_reading(mine))
    lock_data(project=str(demo))

    verify_frozen_inputs(demo)
    mine.write_bytes(b"another dem")

    with pytest.raises(FrozenVerificationError, match=r"1 lockfile mismatch\(es\); first: "):
        verify_frozen_inputs(demo)
