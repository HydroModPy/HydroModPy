"""Nothing that leaves the tree names the machine: no host, no user, no absolute path.

Every JSON, JSON Lines and TOML document and every CSV cell of a copy goes
through the one ``redact`` function; text pages have the private paths
replaced. The sweep reads every text file of the copy. A Parquet file is
never rewritten: one that holds an absolute path refuses the copy, by
column. A copy that would still leak is refused whole.
"""

from __future__ import annotations

import json
import socket
import tarfile
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.publish import publish
from hydromodpy.results.publication import read_published
from tests._helpers.published_runs import make_project, make_sealed_run, make_summary

_TEXT = {".json", ".jsonld", ".jsonl", ".toml", ".md", ".html", ".txt", ".csv"}


def _private_strings(project: Path) -> list[str]:
    workspace = project.parent.parent
    return [str(project), str(workspace), str(Path.home()), f'"{socket.gethostname()}"', "someone"]


def _sweep(copy: Path, private: list[str]) -> list[str]:
    leaks = []
    for path in sorted(copy.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT:
            continue
        text = path.read_text(encoding="utf-8")
        leaks.extend(f"{path.relative_to(copy)}: {item}" for item in private if item in text)
    return leaks


def test_no_text_of_a_copy_names_the_host_the_user_or_a_private_path(tmp_path) -> None:
    project = make_project(tmp_path)
    copy = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("results", "inputs"),
        inputs=inputs_of(project),
    )

    assert _sweep(copy, _private_strings(project)) == []


def test_the_provenance_keeps_what_it_says_and_loses_who_and_where(tmp_path) -> None:
    import json

    project = make_project(tmp_path)
    copy = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        inputs=inputs_of(project),
    )

    provenance = json.loads((copy / "provenance.json").read_text())
    assert "hostname" not in provenance["platform"]
    assert "user" not in provenance["platform"]
    assert provenance["platform"]["cpu"] == "x86_64"
    assert provenance["solver"]["binary_path"] == "<absolute path>"
    assert provenance["sim_id"]


def test_the_frozen_config_keeps_its_tables_with_paths_made_relative(tmp_path) -> None:
    import tomllib

    project = make_project(tmp_path)
    copy = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        inputs=inputs_of(project),
    )

    config = tomllib.loads((copy / "config.toml").read_text())
    assert config["publication"]["license"] == "etalab-2.0"
    assert config["workspace"]["root"] == "<absolute path>"


def test_a_tar_is_swept_like_a_directory(tmp_path) -> None:
    project = make_project(tmp_path)
    archive = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        format="tar",
        inputs=inputs_of(project),
    )
    extracted = tmp_path / "extracted"
    with tarfile.open(archive) as handle:
        handle.extractall(extracted, filter="data")

    assert _sweep(extracted, _private_strings(project)) == []


def test_a_tar_destination_with_a_dot_in_its_name_still_gets_the_tar_suffix(tmp_path) -> None:
    project = make_project(tmp_path)
    archive = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon.v2",
        project_root=project,
        format="tar",
        inputs=inputs_of(project),
    )

    assert archive.name == "nancon.v2.tar"


def test_a_copy_that_would_still_leak_is_refused_whole(tmp_path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    pq.write_table(
        pa.table({"site": ["J0014010"], "path": [f"{project}/runs/x"]}),
        run_dir / "exports" / "where.parquet",
    )

    with pytest.raises(ExportError, match=r"exports/where.parquet: the column 'path'"):
        publish(
            run_dir, tmp_path / "out" / "nancon", project_root=project, inputs=inputs_of(project)
        )
    assert not (tmp_path / "out" / "nancon").exists()
    assert not any(p.name.startswith(".nancon") for p in (tmp_path / "out").iterdir())
    assert read_published(run_dir) == []


def test_a_csv_cell_holding_a_path_is_redacted_like_a_document(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    (run_dir / "exports" / "where.csv").write_text(
        f'site,path,note\nJ0014010,{project}/runs/x,"read /mnt/lab/dem.tif; then {project}"\n'
    )
    (run_dir / "exports" / "events.jsonl").write_text(
        json.dumps({"file": f"{project}/runs/x/a.nc"}) + "\n"
    )

    copy = publish(
        run_dir, tmp_path / "out" / "nancon", project_root=project, inputs=inputs_of(project)
    )

    assert (copy / "exports" / "where.csv").read_text().splitlines() == [
        "site,path,note",
        "J0014010,runs/x,read <absolute path> then .",
    ]
    assert json.loads((copy / "exports" / "events.jsonl").read_text()) == {"file": "runs/x/a.nc"}
    assert _sweep(copy, _private_strings(project)) == []


def test_a_summary_copy_never_carries_the_journal_of_its_publications(tmp_path) -> None:
    project = make_project(tmp_path)
    summary = make_summary(project, error_message="MODFLOW 6 did not converge")

    first = publish(summary, tmp_path / "out" / "o1", project_root=project)
    second = publish(summary, tmp_path / "out" / "o2", project_root=project)

    for copy in (first, second):
        assert not (copy / "published.jsonl").exists()
        assert "published.jsonl" not in json.loads((copy / "PUBLICATION.json").read_text())["files"]
    assert [line.to for line in read_published(summary)][-2:] == [str(first), str(second)]


def test_a_failed_case_naming_the_project_publishes_a_redacted_summary(tmp_path) -> None:
    project = make_project(tmp_path)
    summary = make_summary(
        project,
        error_message=(
            f"See {project}/runs/a/.hmp/scratch/a/mfsim.lst for diagnostics "
            "and /mnt/lab/shared/x.gpkg"
        ),
    )

    copy = publish(summary, tmp_path / "out" / "summary", project_root=project)

    by_case = (copy / "by_case.csv").read_text()
    assert "See runs/a/.hmp/scratch/a/mfsim.lst for diagnostics and <absolute path>" in by_case
    observables = (copy / "report" / "compare" / "a-vs-b" / "observables.csv").read_text()
    assert observables.splitlines()[1] == "Q,runs/a/tables.parquet,runs/a"
    assert "/mnt/lab" not in by_case
    assert _sweep(copy, _private_strings(project)) == []


def test_a_summary_parquet_holding_a_path_is_refused_by_column(tmp_path) -> None:
    project = make_project(tmp_path)
    summary = make_summary(
        project,
        error_message="MODFLOW 6 did not converge",
        parquet_error="/mnt/lab/x/mfsim.lst (host node12)",
    )

    with pytest.raises(ExportError, match=r"by_case.parquet: the column 'error_message'"):
        publish(summary, tmp_path / "out" / "summary", project_root=project)
    assert list((tmp_path / "out").iterdir()) == []
    assert len(read_published(summary)) == 1
