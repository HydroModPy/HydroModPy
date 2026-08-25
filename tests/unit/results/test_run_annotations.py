"""Tags and notes live in the run directory, so an index rebuild keeps them."""

from __future__ import annotations

import json
import uuid

import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.annotations import annotations_path, read_annotations
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.manifest import read_manifest
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME


def _seal_run(catalog: Catalog, name: str) -> str:
    """Register, populate and finalise one run; return its sim_id."""
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        name=name,
        flow_regime="steady",
        n_cells=16,
        n_layers=1,
        bbox=[0.0, 0.0, 10.0, 10.0],
        crs="EPSG:2154",
        config={"flow": {"hk": 1e-5}},
    )
    if registration.zarr is not None:
        registration.zarr.close()
    (catalog.run_dir_for(sid) / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n")
    catalog.finalize(sid, status="completed", duration_s=1.0)
    return sid


@pytest.fixture
def project(tmp_path):
    """A project holding one sealed, annotated run."""
    root = tmp_path / "demo"
    with Catalog(root) as catalog:
        sid = _seal_run(catalog, "alpha")
        catalog.add_tag(sid, "pinned")
        catalog.add_tag(sid, "calibration:0b719164")
        catalog.add_note(sid, "best fit after widening Sy bounds")
    return root


def test_a_tag_lands_next_to_the_manifest(project):
    annotations = read_annotations(project / "runs" / "alpha")

    assert annotations.tags == ("pinned", "calibration:0b719164")
    assert [note.note for note in annotations.notes] == ["best fit after widening Sy bounds"]


def test_the_sidecar_names_its_run(project):
    payload = json.loads(annotations_path(project / "runs" / "alpha").read_text())

    with Catalog(project, read_only=True) as catalog:
        assert payload["sim_id"] == catalog.resolve("alpha")
    assert payload["annotations_version"] == 1


def test_removing_the_last_annotation_removes_the_file(tmp_path):
    root = tmp_path / "demo"
    with Catalog(root) as catalog:
        sid = _seal_run(catalog, "alpha")
        catalog.add_tag(sid, "draft")
        assert annotations_path(catalog.run_dir_for(sid)).is_file()

        catalog.remove_tag(sid, "draft")

        assert not annotations_path(catalog.run_dir_for(sid)).exists()


def test_the_sealed_manifest_ignores_the_mutable_sidecar(project):
    declared = {item["path"] for item in read_manifest(project / "runs" / "alpha")["artifacts"]}

    assert "annotations.json" not in declared


def test_tags_and_notes_survive_an_index_rebuild(project):
    catalog_path_for(project).unlink()

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        sid = catalog.resolve("alpha")
        tags = catalog.backend.fetch_all("SELECT tag FROM tags WHERE sim_id = ?", [sid])
        notes = catalog.backend.fetch_all("SELECT note FROM sim_notes WHERE sim_id = ?", [sid])
    assert {row[0] for row in tags} == {"pinned", "calibration:0b719164"}
    assert [row[0] for row in notes] == ["best fit after widening Sy bounds"]


def test_two_rebuilds_do_not_duplicate_annotations(project):
    rebuild_index(project)
    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        sid = catalog.resolve("alpha")
        tags = catalog.backend.fetch_all("SELECT tag FROM tags WHERE sim_id = ?", [sid])
        notes = catalog.backend.fetch_all("SELECT note FROM sim_notes WHERE sim_id = ?", [sid])
    assert len(tags) == 2
    assert len(notes) == 1


def test_a_broken_sidecar_is_reported_not_ignored(project):
    annotations_path(project / "runs" / "alpha").write_text("{not json")
    catalog_path_for(project).unlink()

    report = rebuild_index(project)

    assert report.indexed == ()
    assert [item.run for item in report.skipped] == ["alpha"]
