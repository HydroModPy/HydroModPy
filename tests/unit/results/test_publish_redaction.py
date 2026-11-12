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
