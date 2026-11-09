"""``publish`` copies a sealed run out of the tree, says what it copied, and leaves a trace.

One function writes the directory and the tar: the copy always holds the
README, the frozen config, the provenance, the inputs, the manifest, the
figures, the exports and the report, a generated RO-Crate and
``PUBLICATION.json``. ``with results`` adds the stores, ``with inputs`` the
install index ``INSTALL.toml`` and the bytes of every file it lists, by content. Logs, attempts, the outcome and the machine state
never leave. The source gets one line in ``published.jsonl``. A project is
published whole or not at all.
"""

from __future__ import annotations

import io
import json
import shutil
import tarfile

import pytest

from hydromodpy.core.exceptions import ConfigMissingError, ExportError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.payload import read_index
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.publish import INPUTS_DIRNAME, publish, publish_project, verify
from hydromodpy.results.publication import read_publication, read_published
from tests._helpers.published_runs import (
    RUN_NAME,
    make_project,
    make_sealed_run,
    make_summary,
)

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
        inputs=inputs_of(project),
    )

    assert (copy / "fields.zarr" / "zarr.json").is_file()
    assert (copy / "tables.parquet" / "simulation.parquet").is_file()
    assert (copy / INPUTS_DIRNAME / f"{sha256_of(observed)}.csv").read_bytes() == (
        observed.read_bytes()
    )
    dem = project.parent.parent / "data" / "dem" / "bdalti_25m.tif"
    assert (copy / INPUTS_DIRNAME / f"{sha256_of(dem)}.tif").read_bytes() == dem.read_bytes()
    index = read_index(copy)
    assert [item.dest for item in index.files] == [
        "data/dem/bdalti_25m.tif",
        "data/hydrometry/J0014010.csv",
    ]
    assert index.file_at("data/hydrometry/J0014010.csv").license == "etalab-2.0"
    assert read_publication(copy).with_ == ["results", "inputs"]
    assert verify(copy) == []


def test_with_inputs_needs_the_index_of_the_run(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    with pytest.raises(ExportError, match="install index"):
        publish(run_dir, tmp_path / "out" / "nancon", project_root=project, with_=("inputs",))
    assert not (tmp_path / "out" / "nancon").exists()


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


def test_public_refuses_by_name_an_input_that_may_not_be_redistributed(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    with pytest.raises(ConfigMissingError) as refused:
        publish(
            run_dir,
            tmp_path / "out" / "nancon",
            project_root=project,
            with_=("inputs",),
            public=True,
            inputs=inputs_of(project),
        )

    message = str(refused.value)
    assert "data/dem/bdalti_25m.tif (file): LicenseRef-undetermined" in message
    assert "J0014010.csv" not in message
    assert not (tmp_path / "out" / "nancon").exists()


def test_public_carries_an_input_whose_sidecar_declares_a_licence(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    dem = project.parent.parent / "data" / "dem" / "bdalti_25m.tif"
    dem.with_name(dem.name + ".json").write_text(
        json.dumps({"source": "file", "sha256": sha256_of(dem), "license": "CC-BY-4.0"}),
        encoding="utf-8",
    )

    copy = publish(
        run_dir,
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("inputs",),
        public=True,
        inputs=inputs_of(project),
    )

    assert read_index(copy).file_at("data/dem/bdalti_25m.tif").license == "CC-BY-4.0"


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


def test_a_project_is_published_member_by_member_in_one_move(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    summary = make_summary(project, error_message=f"See {project}/runs/a/mfsim.lst")
    destination = tmp_path / "out" / "bretagne"

    written = publish_project(project, destination)

    assert written == [destination.resolve() / RUN_NAME, destination.resolve() / "summary"]
    assert {entry.name for entry in destination.iterdir()} == {
        RUN_NAME,
        "summary",
        "PUBLICATION.json",
    }
    assert verify(destination / RUN_NAME) == []
    assert verify(destination / "summary") == []
    assert read_published(run_dir)[-1].to == str(destination.resolve() / RUN_NAME)
    assert read_published(summary)[-1].to == str(destination.resolve() / "summary")


def test_a_project_copy_lists_its_members_in_its_own_publication(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    make_summary(project, error_message="ok")
    destination = tmp_path / "out" / "bretagne"

    publish_project(project, destination)

    root = read_publication(destination)
    assert root.kind == "project"
    assert root.source.rel_dir == "."
    assert root.source.project == project.name
    assert root.files == {}
    assert [(m.name, m.rel_dir) for m in root.members] == [
        (RUN_NAME, f"runs/{RUN_NAME}"),
        ("summary", "summary"),
    ]
    run_member, summary_member = root.members
    assert run_member.manifest_sha256 == sha256_of(run_dir / "manifest.json")
    assert summary_member.manifest_sha256 is None
    assert run_member.publication_sha256 == sha256_of(destination / RUN_NAME / "PUBLICATION.json")
    assert read_publication(destination / RUN_NAME).kind == "run"
    assert read_publication(destination / "summary").kind == "summary"
    assert verify(destination) == []


def test_verify_of_a_project_copy_names_a_member_gone_changed_or_added(tmp_path) -> None:
    project = make_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message="ok")
    destination = tmp_path / "out" / "bretagne"
    publish_project(project, destination)

    shutil.rmtree(destination / RUN_NAME)
    (destination / "summary" / "by_case.csv").write_text("changed\n", encoding="utf-8")
    (destination / "extra").mkdir()

    assert verify(destination) == [
        f"{RUN_NAME}: missing",
        "summary/by_case.csv: digest differs",
        "extra: not listed in PUBLICATION.json",
    ]


def test_verify_of_a_project_copy_names_a_member_whose_publication_changed(tmp_path) -> None:
    project = make_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message="ok")
    destination = tmp_path / "out" / "bretagne"
    publish_project(project, destination, format="tar")

    assert {e.name for e in destination.iterdir()} == {
        f"{RUN_NAME}.tar",
        "summary.tar",
        "PUBLICATION.json",
    }
    assert verify(destination) == []
    publication = destination / "summary.tar"
    with tarfile.open(publication, "r") as archive:
        members = [(m, archive.extractfile(m).read()) for m in archive.getmembers() if m.isfile()]
    publication.unlink()
    with tarfile.open(publication, "w") as archive:
        for member, data in members:
            if member.name.endswith("/PUBLICATION.json"):
                data = data.replace(b'"format": "tar"', b'"format": "tar" ')
                member.size = len(data)
            archive.addfile(member, io.BytesIO(data))

    assert verify(destination) == ["summary.tar: PUBLICATION.json digest differs"]


def test_a_refused_member_leaves_nothing_of_the_project(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    summary = make_summary(
        project, error_message="did not converge", parquet_error=f"See {project}/runs/a/mfsim.lst"
    )
    destination = tmp_path / "out" / "bretagne"

    with pytest.raises(ExportError, match="by_case.parquet: the column 'error_message'"):
        publish_project(project, destination)

    assert list((tmp_path / "out").iterdir()) == []
    assert read_published(run_dir) == []
    assert len(read_published(summary)) == 1


def _declare_a_folder(run_dir, folder) -> str:
    """Add ``folder`` to the tracked inputs of the seal of ``run_dir``; return its digest."""
    from hydromodpy.results.manifest import TrackedInput
    from hydromodpy.results.record import RunRecord
    from hydromodpy.results.storage.digests import sha256_directory

    record = RunRecord.read(run_dir)
    sha256 = sha256_directory(folder)
    tracked = TrackedInput(
        role="hydrometry",
        category="data",
        path="data/hydrometry",
        declared_path="data/hydrometry",
        sha256=sha256,
        portable=True,
    )
    record.model_copy(update={"tracked_inputs": [*record.tracked_inputs, tracked]}).write(run_dir)
    return sha256


def test_a_declared_folder_is_never_copied_whole(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    folder = project.parent.parent / "data" / "hydrometry"
    unread = folder / "J9999999.csv"
    unread.write_text("datetime,value\n2016-01-01,9.0\n", encoding="utf-8")
    sha256 = _declare_a_folder(run_dir, folder)
    sidecar = folder / "J0014010.csv.json"
    sidecar.write_text('{"source": "hubeau"}', encoding="utf-8")

    copy = publish(
        run_dir,
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("inputs",),
        inputs=inputs_of(project),
    )

    stored = {path.name for path in (copy / INPUTS_DIRNAME).iterdir()}
    assert sha256 not in stored
    assert f"{sha256_of(unread)}.csv" not in stored
    assert f"{sha256_of(folder / 'J0014010.csv')}.csv" in stored
    assert f"{sha256_of(sidecar)}.json" in stored
    item = read_index(copy).file_at("data/hydrometry/J0014010.csv")
    assert item.sidecar_sha256 == sha256_of(sidecar)
    assert verify(copy) == []


def test_an_input_the_run_derived_in_its_scratch_is_named_as_such(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    product = tmp_path / "scratch" / "nancon.p1" / "_preprocessing" / "hydrography" / "streams.tif"
    inputs["inputs"].append(
        {
            "variable": "hydrography:hydrography_streams",
            "provider": "hydrography",
            "request": {},
            "path": str(product),
            "sha256": "0" * 64,
        }
    )
    (run_dir / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(ExportError, match="a product the run derived in its scratch"):
        publish(
            run_dir,
            tmp_path / "out" / "nancon",
            project_root=project,
            with_=("inputs",),
            inputs=inputs_of(project),
        )
    assert not (tmp_path / "out" / "nancon").exists()
