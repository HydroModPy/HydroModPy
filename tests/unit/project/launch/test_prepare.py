"""The prepare phase writes the shared ``data/`` folder and locks it once.

A case started by the launcher writes its files and their sidecars straight into the
shared data folder, a station chronicle under its file lock, so the launcher has no
cache to merge. It writes ``hydromodpy.lock`` once, from the sidecars, at the end of
the prepare phase. The workers then run ``--frozen``. A reader is never blocked by a
writer: the sidecars are plain files.

Two cases of one site ask for the same data, so they are never prepared side by
side; a case whose prepare failed is failed and leaves no scratch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.data.provenance.lockfile import read_lockfile_inputs
from hydromodpy.data.provenance.sidecars import FORMER_CACHE_DATABASE, CacheIndex, scan
from hydromodpy.project.launch import plan_project, project_status, run_plan
from tests.unit.project.launch._launch_fakes import CASES, seen, write_behaviour, write_project


@pytest.mark.allow_subprocess
def test_prepare_fills_the_shared_folder_through_the_cases_and_locks_it_once(
    tmp_path: Path, fake_worker: Path
) -> None:
    # One prepare child at a time: the two cases of a site never write side by side.
    project = write_project(tmp_path, sites_extra="[sites.run]\nprepare_parallel = 1\n")
    write_behaviour(project, {case_id: {"register": True} for case_id in CASES})
    plan_project(project)

    report = run_plan(project)

    for case_id in CASES:
        record = seen(project, case_id, "prepare")
        assert (project / record["payload"]).is_file()
        assert record["sidecar"] is True
        assert record["lock"] is True
        assert record["database"] is False
        assert "--frozen" in seen(project, case_id)["flags"]
    assert not (project / "data" / FORMER_CACHE_DATABASE).exists()
    rows = scan(project / "data").rows
    assert {row.station_id for row in rows} == set(CASES)
    events = [json.loads(line) for line in report.journal.read_text().splitlines()]
    lockfiles = [event for event in events if event["event"] == "lockfile"]
    assert len(lockfiles) == 1
    assert lockfiles[0]["path"] == str(project / "hydromodpy.lock")
    assert report.lockfile == project / "hydromodpy.lock"
    first_case = next(i for i, event in enumerate(events) if event["event"] == "case_start")
    assert events.index(lockfiles[0]) < first_case
    locked = read_lockfile_inputs(report.lockfile)
    rows_locked = [item for item in locked if item.source != "file"]
    assert {item.station_id for item in rows_locked} == set(CASES)
    # The DEM every case of the plan declares as a user file is pinned once, by path.
    assert [(item.variable, item.path) for item in locked if item.source == "file"] == [
        ("dem", "dem.tif")
    ]
    assert all(item.license for item in locked)
    assert not (report.journal.parent / "caches").exists()
    assert "merged_entries" not in report.journal.read_text(encoding="utf-8")


def test_a_reader_is_not_blocked_by_a_writer_holding_a_chronicle_lock(tmp_path: Path) -> None:
    data = tmp_path / "ws" / "data"
    folder = data / "discharge"
    folder.mkdir(parents=True)
    payload = folder / "discharge_fake_A_D.csv"
    payload.write_text("date,value\n2000-01-01,1\n", encoding="utf-8")
    writer = CacheIndex(data)
    writer.record(payload, variable="discharge", source="fake", station_id="A")

    with writer.chronicle(folder, "discharge_fake_A"):
        rows = CacheIndex(data).rows(variable="discharge")

    assert [row.station_id for row in rows] == ["A"]


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
