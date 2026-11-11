"""``publish`` copies a sealed run out of the tree, says what it copied, and leaves a trace.

One function writes the directory and the tar: the copy always holds the
README, the frozen config, the provenance, the inputs, the manifest,
``products.json``, the sealed mesh, the figures, the exports and the report,
a generated ``.zenodo.json``, a generated RO-Crate and ``PUBLICATION.json``.
By default it also carries the results (the stores and ``final_state/``) and
the inputs (the install index ``INSTALL.toml`` and the bytes of every file it
lists, by content); an explicit ``with_`` names exactly what it carries.
Logs, attempts, the outcome, the request, the profile, locks, partial files
and the machine state never leave. The source gets one line in
``published.jsonl``. A replay not classed bit is refused, and left out of a
project copy by name. A project is published whole or not at all.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import tarfile
import tomllib

import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.payload.index import read_index
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.publish import (
    INPUTS_DIRNAME,
    PublishedProject,
    _verify_project,
    publish,
    publish_project,
    verify,
)
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
    ".zenodo.json",
    "PUBLICATION.json",
}

BY_DEFAULT = ALWAYS | {
    "products.json",
    "mesh",
    "fields.zarr",
    "tables.parquet",
    "final_state",
    INPUTS_DIRNAME,
    "INSTALL.toml",
}

SOURCE_SIM_ID = "9a4f0000-0000-4000-8000-000000000001"


def _add_products_mesh_and_state(run_dir) -> None:
    """Give a sealed run its products, its sealed mesh, its final state and files never copied."""
    (run_dir / "products.json").write_text('{"products": []}', encoding="utf-8")
    (run_dir / "mesh").mkdir()
    (run_dir / "mesh" / "grid.json").write_text('{"nrow": 2}', encoding="utf-8")
    (run_dir / "final_state").mkdir()
    (run_dir / "final_state" / "head.bin").write_bytes(b"\x00\x01")
    (run_dir / "final_state" / "head.bin.part").write_bytes(b"\x00")
    (run_dir / "mesh" / "grid.json.lock").write_text("{}", encoding="utf-8")
    (run_dir / "request.json").write_text("{}", encoding="utf-8")
    (run_dir / "profile.json").write_text("{}", encoding="utf-8")


def _make_replay(run_dir, *, basis: str, class_: str | None, of: str = SOURCE_SIM_ID) -> None:
    """Rewrite the lineage of the seal of *run_dir* as a replay of the run *of*."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    replay = {
        "of": of,
        "source": "copy" if basis == "none" else "run",
        "source_version": "2.1.0",
        "basis": basis,
    }
    if class_ is not None:
        replay["class"] = class_
    if class_ == "deviation":
        replay["differs"] = {"fields/head": {"max_abs": 1e-4, "rel_l2": 2e-6, "precision": "exact"}}
    manifest["lineage"] = {**manifest["lineage"], "kind": "replay", "replay": replay}
    manifest["run"]["sim_id"] = "1b2c0000-0000-4000-8000-000000000002"
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_a_copy_carries_its_results_and_inputs_by_default_and_never_its_machine_state(
    tmp_path,
) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    _add_products_mesh_and_state(run_dir)

    copy = publish(
        run_dir, tmp_path / "out" / "nancon", project_root=project, inputs=inputs_of(project)
    )

    assert {entry.name for entry in copy.iterdir()} == BY_DEFAULT
    assert (copy / "final_state" / "head.bin").read_bytes() == b"\x00\x01"
    assert (copy / "mesh" / "grid.json").is_file()
    for left_out in (
        ".hmp",
        "logs",
        "attempts",
        "outcome.json",
        "published.jsonl",
        "request.json",
        "profile.json",
        "final_state/head.bin.part",
        "mesh/grid.json.lock",
    ):
        assert not (copy / left_out).exists(), left_out
    assert read_publication(copy).with_ == ["results", "inputs"]
    crate = json.loads((copy / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    assert ".zenodo.json" in {node.get("@id") for node in crate["@graph"]}
    zenodo = json.loads((copy / ".zenodo.json").read_text(encoding="utf-8"))
    assert zenodo["upload_type"] == "dataset"
    assert zenodo["creators"] == [{"name": "A. Author"}]
    assert zenodo["license"] == "etalab-2.0"
    assert verify(copy) == []


@pytest.mark.parametrize(
    ("with_", "present", "absent"),
    [
        pytest.param(
            ("inputs",),
            {INPUTS_DIRNAME, "INSTALL.toml", "products.json", "mesh"},
            {"fields.zarr", "tables.parquet", "final_state"},
            id="without_results",
        ),
        pytest.param(
            ("results",),
            {"fields.zarr", "tables.parquet", "final_state", "products.json", "mesh"},
            {INPUTS_DIRNAME, "INSTALL.toml"},
            id="without_inputs",
        ),
    ],
)
def test_an_explicit_with_leaves_the_other_part_out(tmp_path, with_, present, absent) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    _add_products_mesh_and_state(run_dir)

    copy = publish(
        run_dir,
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=with_,
        inputs=inputs_of(project),
    )

    names = {entry.name for entry in copy.iterdir()}
    assert present <= names
    assert not absent & names
    assert read_publication(copy).with_ == list(with_)
    assert verify(copy) == []


def test_publication_names_the_source_and_every_file_it_copied(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    copy = publish(
        run_dir, tmp_path / "out" / "nancon", project_root=project, inputs=inputs_of(project)
    )

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

    copy = publish(run_dir, target, project_root=project, inputs=inputs_of(project))

    (line,) = read_published(run_dir)
    assert line.kind == "copy"
    assert line.to == str(target.resolve())
    assert line.format == "dir"
    assert line.publication_sha256 == sha256_of(copy / "PUBLICATION.json")


def test_a_copy_loses_deliver_to_and_its_source_keeps_it(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    block = (
        '\n[[export]]\nvariables = ["head"]\nfile = "head_last.tif"\n'
        'deliver_to = ["/data/depot/"]\n'
    )
    for name in ("config.toml", "config.resolved.toml"):
        path = run_dir / name
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        path.write_text(before + block, encoding="utf-8")

    copy = publish(
        run_dir, tmp_path / "out" / "nancon", project_root=project, inputs=inputs_of(project)
    )

    for name in ("config.toml", "config.resolved.toml"):
        copied = tomllib.loads((copy / name).read_text(encoding="utf-8"))
        source = tomllib.loads((run_dir / name).read_text(encoding="utf-8"))
        assert copied["export"] == [{"variables": ["head"], "file": "head_last.tif"}]
        assert source["export"] == [
            {"variables": ["head"], "file": "head_last.tif", "deliver_to": ["/data/depot/"]}
        ]
    assert verify(copy) == []


def test_the_crate_lists_the_copied_files_under_the_declared_licence(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    copy = publish(
        run_dir, tmp_path / "out" / "nancon", project_root=project, inputs=inputs_of(project)
    )

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


@pytest.mark.parametrize("with_", [None, ("inputs",)], ids=["by_default", "with_inputs"])
def test_carrying_inputs_needs_the_index_of_the_run(tmp_path, with_) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    extra = {} if with_ is None else {"with_": with_}

    with pytest.raises(ExportError, match="install index"):
        publish(run_dir, tmp_path / "out" / "nancon", project_root=project, **extra)
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
    copy = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        inputs=inputs_of(project),
    )

    (copy / "exports" / "discharge.csv").write_text("tampered\n")
    (copy / "extra.txt").write_text("added\n")

    assert verify(copy) == [
        "exports/discharge.csv: digest differs",
        "extra.txt: not listed in PUBLICATION.json",
    ]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_public_warns_without_a_licence(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    project = make_project(tmp_path, license=None)
    run_dir = make_sealed_run(project, license=None)

    copy = publish(
        run_dir,
        tmp_path / "out" / "nancon",
        project_root=project,
        public=True,
        inputs=inputs_of(project),
    )

    assert any("declares no [publication] license" in message for message in _warnings(caplog))
    assert (copy / "PUBLICATION.json").is_file()
    assert read_published(run_dir)
    assert verify(copy) == []
    assert "LicenseRef-undetermined" in (copy / "ro-crate-metadata.json").read_text()


def test_a_summary_copy_warns_without_a_licence_and_is_written(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    project = make_project(tmp_path, license=None)
    make_summary(project, error_message="the solver stopped")

    copies = publish_project(project, tmp_path / "out", public=True)

    assert any("declares no [publication] license" in message for message in _warnings(caplog))
    assert (tmp_path / "out" / "summary").is_dir()
    assert copies.copies


def test_public_goes_through_with_a_licence(tmp_path) -> None:
    project = make_project(tmp_path)
    copy = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("results",),
        public=True,
    )
    assert (copy / "PUBLICATION.json").is_file()


def test_public_warns_and_names_an_input_without_a_licence(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)

    copy = publish(
        run_dir,
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("inputs",),
        public=True,
        inputs=inputs_of(project),
    )

    message = "\n".join(_warnings(caplog))
    assert "data/dem/bdalti_25m.tif (file): LicenseRef-undetermined" in message
    assert "J0014010.csv" not in message
    assert (copy / "PUBLICATION.json").is_file()
    assert read_index(copy).file_at("data/dem/bdalti_25m.tif").license == "LicenseRef-undetermined"
    assert read_index(copy).file_at("data/hydrometry/J0014010.csv").license == "etalab-2.0"


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
        publish(unsealed, tmp_path / "out" / "x", project_root=project, inputs=inputs_of(project))
    with pytest.raises(ExportError, match="not an empty directory"):
        publish(run_dir, used, project_root=project, inputs=inputs_of(project))
    assert (used / "keep.txt").read_text() == "mine"


def test_a_project_is_published_member_by_member_in_one_move(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    summary = make_summary(project, error_message=f"See {project}/runs/a/mfsim.lst")
    destination = tmp_path / "out" / "bretagne"

    written = publish_project(project, destination, inputs=inputs_of(project))

    assert written == PublishedProject(
        copies=[destination.resolve() / RUN_NAME, destination.resolve() / "summary"],
        left_out=[],
    )
    assert {entry.name for entry in destination.iterdir()} == {
        RUN_NAME,
        "summary",
        "PUBLICATION.json",
        ".zenodo.json",
    }
    assert (destination / RUN_NAME / "fields.zarr").is_dir()
    assert (destination / RUN_NAME / "INSTALL.toml").is_file()
    assert (destination / "summary" / ".zenodo.json").is_file()
    assert verify(destination / RUN_NAME) == []
    assert verify(destination / "summary") == []
    assert read_published(run_dir)[-1].to == str(destination.resolve() / RUN_NAME)
    assert read_published(summary)[-1].to == str(destination.resolve() / "summary")


def test_a_project_copy_lists_its_members_in_its_own_publication(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    make_summary(project, error_message="ok")
    destination = tmp_path / "out" / "bretagne"

    publish_project(project, destination, inputs=inputs_of(project))

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
    assert read_publication(destination / "summary").with_ == []
    zenodo = json.loads((destination / ".zenodo.json").read_text(encoding="utf-8"))
    assert zenodo["title"] == project.name
    assert zenodo["upload_type"] == "dataset"
    assert verify(destination) == []


def test_verify_of_a_project_copy_names_a_member_gone_changed_or_added(tmp_path) -> None:
    project = make_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message="ok")
    destination = tmp_path / "out" / "bretagne"
    publish_project(project, destination, inputs=inputs_of(project))

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
    publish_project(project, destination, format="tar", inputs=inputs_of(project))

    assert {e.name for e in destination.iterdir()} == {
        f"{RUN_NAME}.tar",
        "summary.tar",
        "PUBLICATION.json",
        ".zenodo.json",
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
        publish_project(project, destination, inputs=inputs_of(project))

    assert list((tmp_path / "out").iterdir()) == []
    assert read_published(run_dir) == []
    assert len(read_published(summary)) == 1


def _declare_a_folder(run_dir, folder) -> str:
    """Add ``folder`` to the tracked inputs of the seal of ``run_dir``; return its digest."""
    from hydromodpy.results.record.manifest import TrackedInput
    from hydromodpy.results.record.record import RunRecord
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


def test_verify_of_a_project_copy_accepts_the_generated_views_at_its_root(tmp_path) -> None:
    project = make_project(tmp_path)
    make_sealed_run(project)
    destination = tmp_path / "out" / "bretagne"
    publish_project(project, destination, inputs=inputs_of(project))
    (destination / "stray.txt").write_text("added\n", encoding="utf-8")

    assert (destination / ".zenodo.json").is_file()
    assert _verify_project(destination, read_publication(destination)) == [
        "stray.txt: not listed in PUBLICATION.json"
    ]


DEVIATION_REFUSAL = (
    f"runs/{RUN_NAME} replays runs/source and its values differ from the seal (class "
    "deviation: fields/head). A published copy states that it gives the sealed numbers, so it "
    "is not published. Publish runs/source itself, or a replay classed bit."
)
CLASSLESS_REFUSAL = (
    f"runs/{RUN_NAME} replays a copy that carried no values, so it was never compared with "
    "the seal. A published copy states that it gives the sealed numbers: replay a copy that "
    "carries its results, or publish the source run itself."
)


def _project_with_a_replay(tmp_path, *, basis: str, class_: str | None):
    """Return a project whose run replays a sealed ``runs/source``, and that replay."""
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    source = project / "runs" / "source"
    shutil.copytree(run_dir, source)
    _make_replay(run_dir, basis=basis, class_=class_)
    return project, run_dir


@pytest.mark.parametrize(
    ("basis", "class_", "refusal"),
    [
        pytest.param("float64", "deviation", DEVIATION_REFUSAL, id="deviation"),
        pytest.param("none", None, CLASSLESS_REFUSAL, id="classless"),
        pytest.param("float64", "bit", None, id="bit"),
        pytest.param(None, None, None, id="no_lineage"),
    ],
)
def test_a_replay_is_published_only_when_classed_bit(tmp_path, basis, class_, refusal) -> None:
    if basis is None:
        project = make_project(tmp_path)
        run_dir = make_sealed_run(project)
    else:
        project, run_dir = _project_with_a_replay(tmp_path, basis=basis, class_=class_)
    target = tmp_path / "out" / "copy"

    if refusal is None:
        copy = publish(run_dir, target, project_root=project, with_=("results",))
        assert verify(copy) == []
        return
    with pytest.raises(ExportError) as refused:
        publish(run_dir, target, project_root=project, with_=("results",))
    assert str(refused.value) == refusal
    assert not target.exists()
    assert read_published(run_dir) == []


def test_a_project_copy_leaves_a_replay_not_classed_bit_out_and_names_it(tmp_path, caplog) -> None:
    project, run_dir = _project_with_a_replay(tmp_path, basis="float64", class_="deviation")
    destination = tmp_path / "out" / "bretagne"

    with caplog.at_level("WARNING"):
        published = publish_project(project, destination, with_=("results",))

    assert published.copies == [destination.resolve() / "source"]
    assert published.left_out == [(f"runs/{RUN_NAME}", DEVIATION_REFUSAL)]
    assert DEVIATION_REFUSAL in caplog.text
    assert not (destination / RUN_NAME).exists()
    assert [m.name for m in read_publication(destination).members] == ["source"]
    assert read_published(run_dir) == []
    assert verify(destination) == []
