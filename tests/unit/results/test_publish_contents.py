"""``publish`` copies a sealed run out of the tree, says what it copied, and leaves a trace.

One function writes the directory and the tar: the copy always holds the
README, the frozen config, the provenance, the inputs, the manifest, the
figures, the exports and the report, a generated RO-Crate and
``PUBLICATION.json``. ``with results`` adds the stores, ``with inputs`` the
input bytes by content. Logs, attempts, the outcome and the machine state
never leave. The source gets one line in ``published.jsonl``.
"""

from __future__ import annotations

import json
import tarfile

import pytest

from hydromodpy.core.exceptions import ConfigMissingError, ExportError
from hydromodpy.results.export.publish import INPUTS_DIRNAME, publish, verify
from hydromodpy.results.ledger import sha256_of
from hydromodpy.results.publication import read_publication, read_published
from tests.unit.results._published_run import RUN_NAME, make_project, make_sealed_run

ALWAYS = {
    "README.md",
    "config.toml",
    "provenance.json",
    "inputs.json",
    "manifest.json",
    "figures",
    "exports",
    "report",
    "ro-crate-metadata.json",
    "PUBLICATION.json",
}


def test_a_copy_holds_the_run_and_never_its_machine_state(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    copy = publish(run_dir, tmp_path / "out" / "nancon", project_root=project)

    assert {entry.name for entry in copy.iterdir()} == ALWAYS
    for left_out in (".hmp", "logs", "attempts", "outcome.json", "published.jsonl", "fields.zarr"):
        assert not (copy / left_out).exists(), left_out


def test_publication_names_the_source_and_every_file_it_copied(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    copy = publish(run_dir, tmp_path / "out" / "nancon", project_root=project)

    publication = read_publication(copy)
    assert publication.source.project == "bretagne_k"
    assert publication.source.rel_dir == f"runs/{RUN_NAME}"
    assert (
        publication.source.sim_id
        == json.loads((run_dir / "manifest.json").read_text())["run"]["sim_id"]
    )
    assert publication.manifest_sha256 == sha256_of(run_dir / "manifest.json")
    assert publication.label == "calibrated"
    assert publication.format == "dir"
    files = {p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()}
    assert set(publication.files) == files - {"PUBLICATION.json"}
    assert all(sha256_of(copy / name) == digest for name, digest in publication.files.items())
    assert verify(copy) == []


def test_the_source_remembers_where_its_copy_went(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    target = tmp_path / "out" / "nancon"

    copy = publish(run_dir, target, project_root=project)

    (line,) = read_published(run_dir)
    assert line.to == str(target.resolve())
    assert line.format == "dir"
    assert line.publication_sha256 == sha256_of(copy / "PUBLICATION.json")


def test_the_crate_lists_the_copied_files_under_the_declared_licence(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    copy = publish(run_dir, tmp_path / "out" / "nancon", project_root=project)

    crate = json.loads((copy / "ro-crate-metadata.json").read_text())
    ids = {node.get("@id") for node in crate["@graph"]}
    assert {"figures/heads.png", "exports/discharge.csv", "report/index.html"} <= ids
    assert "https://spdx.org/licenses/etalab-2.0" in json.dumps(crate)


def test_with_results_and_inputs_take_the_stores_and_the_bytes_by_content(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    observed = project.parent.parent / "data" / "hydrometry" / "J0014010.csv"

    copy = publish(
        run_dir,
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("results", "inputs"),
    )

    assert (copy / "fields.zarr" / "zarr.json").is_file()
    assert (copy / "tables.parquet" / "simulation.parquet").is_file()
    assert (copy / INPUTS_DIRNAME / f"{sha256_of(observed)}.csv").read_bytes() == (
        observed.read_bytes()
    )
    dem = project.parent.parent / "data" / "dem" / "bdalti_25m.tif"
    assert (copy / INPUTS_DIRNAME / f"{sha256_of(dem)}.tif").read_bytes() == dem.read_bytes()
    assert read_publication(copy).with_ == ["results", "inputs"]


def test_a_tar_is_the_same_copy_under_the_name_of_the_run(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    archive = publish(
        run_dir, tmp_path / "out" / "nancon", project_root=project, format="tar", with_=("results",)
    )

    assert archive.name == "nancon.tar"
    with tarfile.open(archive) as handle:
        names = handle.getnames()
    assert all(name.startswith(f"{RUN_NAME}/") for name in names)
    assert f"{RUN_NAME}/PUBLICATION.json" in names
    assert f"{RUN_NAME}/fields.zarr/zarr.json" in names
    assert verify(archive) == []
    assert read_published(run_dir)[0].format == "tar"


def test_verify_names_a_file_that_changed_or_appeared(tmp_path) -> None:
    project = make_project(tmp_path)
    copy = publish(make_sealed_run(project), tmp_path / "out" / "nancon", project_root=project)

    (copy / "exports" / "discharge.csv").write_text("tampered\n")
    (copy / "extra.txt").write_text("added\n")

    assert verify(copy) == [
        "exports/discharge.csv: digest differs",
        "extra.txt: not listed in PUBLICATION.json",
    ]


def test_public_is_refused_without_a_licence(tmp_path) -> None:
    project = make_project(tmp_path, license=None)
    run_dir = make_sealed_run(project, license=None)

    with pytest.raises(ConfigMissingError, match=r"\[publication\] license"):
        publish(run_dir, tmp_path / "out" / "nancon", project_root=project, public=True)
    assert not (tmp_path / "out" / "nancon").exists()
    assert read_published(run_dir) == []


def test_public_goes_through_with_a_licence(tmp_path) -> None:
    project = make_project(tmp_path)
    copy = publish(
        make_sealed_run(project), tmp_path / "out" / "nancon", project_root=project, public=True
    )
    assert (copy / "PUBLICATION.json").is_file()


def test_an_unsealed_run_and_a_used_destination_are_refused(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    unsealed = project / "runs" / "failed_case"
    unsealed.mkdir()
    (unsealed / "outcome.json").write_text('{"status": "failed"}')
    used = tmp_path / "used"
    used.mkdir()
    (used / "keep.txt").write_text("mine")

    with pytest.raises(ExportError, match="only a completed, sealed run"):
        publish(unsealed, tmp_path / "out" / "x", project_root=project)
    with pytest.raises(ExportError, match="not an empty directory"):
        publish(run_dir, used, project_root=project)
    assert (used / "keep.txt").read_text() == "mine"
