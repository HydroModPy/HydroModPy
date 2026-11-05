"""The prepare phase is the one writer of the shared ``cache.duckdb``.

A case started by the launcher reads the shared cache read-only, one query at
a time, and registers what it fetches in a private cache; the launcher merges
that private cache into the shared one once the case has ended, and writes
``hydromodpy.lock`` once, at the end of the prepare phase. The workers then
run ``--frozen``. ``hmp data`` reads and the ``--frozen`` check open the
cache read-only.

Two cases of one site ask for the same data, so they are never prepared side by
side; a case whose prepare failed is failed and leaves no scratch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from hydromodpy.data.registry.catalog_duckdb import (
    PRIVATE_CACHE_ENV,
    DataCatalogDuckDB,
    merge_private_cache,
)
from hydromodpy.project.launch import plan_project, project_status, run_plan
from tests.unit.project.launch._launch_fakes import CASES, seen, write_behaviour, write_project


def _register(catalog: DataCatalogDuckDB, payload: Path, station: str) -> None:
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text("date,value\n2000-01-01,1\n", encoding="utf-8")
    catalog.register(variable="discharge", source="fake", station_id=station, file_path=payload)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_launched_case_writes_its_private_cache_and_reads_the_shared_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "ws" / "data"
    shared_path = data / "cache.duckdb"
    with DataCatalogDuckDB(shared_path) as shared:
        _register(shared, data / "discharge" / "A.csv", "A")
    before = _digest(shared_path)
    private_path = tmp_path / "jobs" / "x" / "data-cache.duckdb"
    monkeypatch.setenv(PRIVATE_CACHE_ENV, str(private_path))

    with DataCatalogDuckDB(shared_path) as layered:
        assert layered.layered
        assert layered.find_cached(variable="discharge", source="fake", station_id="A")
        _register(layered, data / "discharge" / "B.csv", "B")
        found = layered.find_cached(variable="discharge", source="fake", station_id="B")
        assert found is not None
        assert layered.resolve_path(found.file_path) == data / "discharge" / "B.csv"
        listed = set(layered.list_entries(variable="discharge")["station_id"])
        assert listed == {"A", "B"}
        # The shared file is not held between queries: a writer gets in at once.
        duckdb.connect(str(shared_path)).close()

    assert _digest(shared_path) == before
    assert private_path.is_file()


def test_the_launcher_merges_a_private_cache_into_the_shared_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "ws" / "data"
    shared_path = data / "cache.duckdb"
    private_path = tmp_path / "jobs" / "x" / "data-cache.duckdb"
    monkeypatch.setenv(PRIVATE_CACHE_ENV, str(private_path))
    with DataCatalogDuckDB(shared_path) as layered:
        _register(layered, data / "discharge" / "B.csv", "B")
    monkeypatch.delenv(PRIVATE_CACHE_ENV)

    assert merge_private_cache(shared_path, private_path) == 1

    with DataCatalogDuckDB(shared_path, read_only=True) as shared:
        entry = shared.find_cached(variable="discharge", source="fake", station_id="B")
        assert entry is not None
        assert shared.resolve_path(entry.file_path) == data / "discharge" / "B.csv"
        (data / "discharge" / "C.csv").write_text("date,value\n", encoding="utf-8")
        refused = shared.register(
            variable="discharge",
            source="fake",
            station_id="C",
            file_path=data / "discharge" / "C.csv",
        )
        assert refused == -1
        assert shared.find_cached(variable="discharge", source="fake", station_id="C") is None


@pytest.mark.allow_subprocess
def test_prepare_fills_the_shared_cache_through_the_launcher_and_locks_it_once(
    tmp_path: Path, fake_worker: Path
) -> None:
    # One prepare child at a time: the shared file may then change only between children.
    project = write_project(tmp_path, sites_extra="[sites.run]\nprepare_parallel = 1\n")
    write_behaviour(project, {case_id: {"register": True} for case_id in CASES})
    plan_project(project)

    report = run_plan(project)

    for case_id in CASES:
        record = seen(project, case_id, "prepare")
        assert record["layered"] is True
        assert record["shared_untouched"] is True
        assert record["database"] == [record["env"]["HMP_DATA_CACHE_PRIVATE"]]
        assert "--frozen" in seen(project, case_id)["flags"]
    with DataCatalogDuckDB(project / "data" / "cache.duckdb", read_only=True) as shared:
        stations = set(shared.list_entries(variable="discharge")["station_id"])
    assert stations == set(CASES)
    events = [json.loads(line) for line in report.journal.read_text().splitlines()]
    lockfiles = [event for event in events if event["event"] == "lockfile"]
    assert len(lockfiles) == 1
    assert lockfiles[0]["path"] == str(project / "hydromodpy.lock")
    assert report.lockfile == project / "hydromodpy.lock"
    first_case = next(i for i, event in enumerate(events) if event["event"] == "case_start")
    assert events.index(lockfiles[0]) < first_case
    assert not any((report.journal.parent / "caches").glob("*/data-cache.duckdb"))


def test_hmp_data_reads_open_the_cache_read_only(tmp_path: Path, monkeypatch) -> None:
    from hydromodpy.cli._workers import data as data_worker

    workspace = tmp_path / "ws"
    with DataCatalogDuckDB(workspace / "data" / "cache.duckdb") as cache:
        _register(cache, workspace / "data" / "discharge" / "A.csv", "A")
    monkeypatch.setattr("hydromodpy.cli.helpers.resolve_workspace", lambda value: workspace)
    holder = duckdb.connect(str(workspace / "data" / "cache.duckdb"), read_only=True)
    try:
        rows = data_worker.list_data_cache("ws", variable="discharge", provider=None)
    finally:
        holder.close()

    assert list(rows["station_id"]) == ["A"]


@pytest.mark.allow_subprocess
def test_two_cases_of_one_site_are_never_prepared_side_by_side(
    tmp_path: Path, fake_worker: Path
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nprepare_parallel = 4\n")
    write_behaviour(
        project,
        {case: {"prepare_sleep": 0.6} for case in ("alpha-base", "alpha-k2e_5", "beta-base")},
    )
    plan_project(project)

    run_plan(project, until="data")

    def window(case_id: str) -> tuple[float, float]:
        record = seen(project, case_id, "prepare")
        return record["started"], record["ended"]

    for site in ("alpha", "beta"):
        first, second = sorted([window(f"{site}-base"), window(f"{site}-k2e_5")])
        assert first[1] <= second[0], f"the two cases of {site} were prepared together"
    # Two sites still prepare side by side.
    alpha, beta = window("alpha-base"), window("beta-base")
    assert max(alpha[0], beta[0]) < min(alpha[1], beta[1])


@pytest.mark.allow_subprocess
def test_a_case_whose_prepare_failed_is_failed_and_leaves_no_scratch(
    tmp_path: Path, fake_worker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The machine scratch of the shell must not move the folder this test watches.
    monkeypatch.delenv("HMP_SCRATCH_ROOT", raising=False)
    project = write_project(tmp_path)
    write_behaviour(project, {"alpha-base": {"prepare": "fail"}})
    plan_project(project)

    report = run_plan(project)

    status = {row.case_id: row.status for row in project_status(project).rows}
    assert status["alpha-base"] == "failed"
    assert status["beta-base"] == "completed"
    assert {case.case_id for case in report.cases if case.status == "failed"} == {"alpha-base"}
    scratch = project / ".hmp" / "scratch"
    assert not scratch.exists() or not list(scratch.glob("alpha-base.p*"))
