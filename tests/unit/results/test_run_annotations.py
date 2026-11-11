"""Tags and notes live in the run directory, so the index reads them from there."""

from __future__ import annotations

import json

import pytest

from hydromodpy.results.annotations import (
    Annotations,
    Note,
    annotations_path,
    read_annotations,
    write_annotations,
)
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import index_new_runs, rebuild_index
from hydromodpy.results.record.manifest import read_manifest
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


def test_a_tag_lands_next_to_the_manifest(project):
    root, sid = project
    payload = json.loads(annotations_path(root / "runs" / "alpha").read_text(encoding="utf-8"))
    assert payload["sim_id"] == sid
    assert payload["tags"] == ["pinned", "keep"]


def test_the_sealed_manifest_ignores_the_mutable_sidecar(project):
    root, _sid = project
    manifest = read_manifest(root / "runs" / "alpha")
    assert all(entry["path"] != "annotations.json" for entry in manifest["artifacts"])


def test_tags_and_notes_come_back_with_the_index(project):
    root, sid = project
    rebuild_index(root)

    assert _tags_and_notes(root, sid) == (["keep", "pinned"], ["best fit"])


def test_two_rebuilds_do_not_duplicate_annotations(project):
    root, sid = project
    rebuild_index(root)
    rebuild_index(root)

    assert _tags_and_notes(root, sid) == (["keep", "pinned"], ["best fit"])


def test_removing_a_tag_on_disk_is_picked_up_by_the_next_pass(project):
    root, sid = project
    rebuild_index(root)
    write_annotations(root / "runs" / "alpha", Annotations(sim_id=sid, tags=("keep",)))

    report = index_new_runs(root)

    assert report.indexed == ("runs/alpha",)
    assert _tags_and_notes(root, sid) == (["keep"], [])


def test_a_cleared_file_reads_back_with_no_tag_and_the_sim_id_of_the_run(tmp_path):
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "alpha")
    run_dir = root / "runs" / "alpha"
    write_annotations(run_dir, Annotations(tags=("pinned",)))
    write_annotations(run_dir, Annotations())

    assert read_annotations(run_dir) == Annotations(sim_id=sid)


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
