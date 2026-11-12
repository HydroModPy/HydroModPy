"""Tags and notes live in the run directory, so the index reads them from there."""

from __future__ import annotations

import pytest

from hydromodpy.results.annotations import Annotations, Note, annotations_path, write_annotations
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


@pytest.fixture
def project(tmp_path):
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "alpha")
    write_annotations(
        root / "runs" / "alpha",
        Annotations(
            sim_id=sid,
            tags=("pinned", "keep"),
            notes=(Note(text="best fit", at="2026-07-25T22:24:31+00:00"),),
        ),
    )
    return root, sid


def _tags_and_notes(root, sid: str) -> tuple[list[str], list[str]]:
    with Catalog(root) as catalog:
        tags = [r[0] for r in catalog.backend.fetch_all("SELECT tag FROM tags ORDER BY tag")]
        notes = [r[0] for r in catalog.backend.fetch_all("SELECT note FROM sim_notes")]
    return tags, notes


def test_a_broken_sidecar_costs_a_warning_and_the_seal_stands(project, caplog):
    root, sid = project
    target = annotations_path(root / "runs" / "alpha")
    target.write_text("[]", encoding="utf-8")

    report = rebuild_index(root)

    assert report.skipped == ()
    assert report.indexed == ("runs/alpha",)
    assert _tags_and_notes(root, sid) == ([], [])
    assert any(str(target) in record.getMessage() for record in caplog.records)
    assert target.read_text(encoding="utf-8") == "[]"
