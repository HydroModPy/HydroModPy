"""``publish`` copies a sealed run out of the tree, says what it copied, and leaves a trace.
It also keeps the machine out of the copy: no host, no user, no absolute path.

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
project copy by name. A project is published whole or not at all. Every JSON, JSON Lines, TOML and CSV cell goes
through ``redact``, and a Parquet file holding an absolute path refuses the copy, by column.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import socket
import tarfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.payload.index import read_index
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
    # Products, sealed mesh and final state, plus files that are never copied.
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
    # Rewrite the lineage of the seal as a replay of the run named by `of`.
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


def test_default_copy(tmp_path) -> None:
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
def test_explicit_with(tmp_path, with_, present, absent) -> None:
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


@pytest.mark.parametrize("with_", [None, ("inputs",)], ids=["by_default", "with_inputs"])
def test_inputs_need_the_install_index(tmp_path, with_) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    extra = {} if with_ is None else {"with_": with_}

    with pytest.raises(ExportError, match="install index"):
        publish(run_dir, tmp_path / "out" / "nancon", project_root=project, **extra)
    assert not (tmp_path / "out" / "nancon").exists()


def test_tar_copy(tmp_path) -> None:
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


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_public_without_a_licence(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
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


def test_summary_without_a_licence(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    project = make_project(tmp_path, license=None)
    make_summary(project, error_message="the solver stopped")

    copies = publish_project(project, tmp_path / "out", public=True)

    assert any("declares no [publication] license" in message for message in _warnings(caplog))
    assert (tmp_path / "out" / "summary").is_dir()
    assert copies.copies


def test_input_without_a_licence(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
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


def test_input_licence_from_its_sidecar(tmp_path) -> None:
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


def test_unsealed_run_and_used_destination(tmp_path) -> None:
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


def test_verify_project_copy(tmp_path) -> None:
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


def test_verify_project_tar_copy(tmp_path) -> None:
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


def test_refused_member_leaves_nothing(tmp_path) -> None:
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


def test_scratch_input_is_refused(tmp_path) -> None:
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
    # A project whose run replays a sealed runs/source.
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
def test_replay_of_a_run(tmp_path, basis, class_, refusal) -> None:
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


def test_project_copy_leaves_a_deviating_replay_out(tmp_path, caplog) -> None:
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


def test_leaking_parquet_refuses_the_copy(tmp_path) -> None:
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


def test_csv_and_jsonl_paths_are_redacted(tmp_path) -> None:
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


def test_summary_parquet_refused_by_column(tmp_path) -> None:
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
