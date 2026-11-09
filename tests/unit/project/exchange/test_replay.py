"""The frozen configuration of a published copy replays from the bytes the copy carries.

``hmp run <copy>/config.toml --frozen`` checks every file of the install index
against ``inputs/`` and points the field of each recorded role at those bytes:
a declared file is read where it is stored, a declared folder is rebuilt from
the files of the index that sit in it, with its station rows, and never holds
a station the run did not read. A missing file, bytes with another digest or
a file a provider delivered refuse the replay before anything runs. The run
goes to the project ``-w`` names. The full chain, a solve included, is
``tests/e2e/test_replay_from_archive_without_workspace.py``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.core.payload import INSTALL_FILENAME, read_index, stored_name
from hydromodpy.project.exchange.replay import (
    ReplayInputError,
    published_copy_of,
    replay_payload,
)
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.publish import INPUTS_DIRNAME, publish
from hydromodpy.results.manifest import InputEntry, TrackedInput
from tests._helpers.cli_runner import CliRunner
from tests._helpers.run_records import make_record
from tests.unit.catalog._shared_run import (
    CUSTOM_FILE,
    CUSTOM_LOC,
    SERIES,
    UNREAD_FILE,
    make_shared_run,
    make_workspace,
    sha256_of,
)

RUN_NAME = "nancon_step5_export"

_CONFIG = """\
[workflow]
mode = "simulation"

[simulation]
name = "nancon_step5_export"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["dem", "hydrometry"]

[[data.dem.sources]]
source = "file"
path = "dem.tif"

[[data.hydrometry.sources]]
source = "file"
path = "hydrometry"
station_ids = ["NANCON"]
"""


def _published(tmp_path: Path) -> Path:
    """Publish a run that read a user station file in a declared folder and a declared DEM."""
    workspace = tmp_path / "ws"
    project = make_workspace(workspace)
    folder = workspace / "data" / "hydrometry"
    folder.mkdir(parents=True)
    station = folder / CUSTOM_FILE
    station.write_text(SERIES, encoding="utf-8")
    (folder / UNREAD_FILE).write_text(SERIES, encoding="utf-8")
    (folder / "hydrometry_custom_LOC.csv").write_text(CUSTOM_LOC, encoding="utf-8")
    dem = workspace / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"the dem bytes")
    run_dir = project / "runs" / RUN_NAME
    run_dir.mkdir(parents=True)
    make_record(
        inputs=[
            InputEntry(
                variable="hydrometry:discharge",
                provider="custom",
                request={"station": "NANCON"},
                path=f"data/hydrometry/{CUSTOM_FILE}",
                sha256=sha256_of(station),
            )
        ],
        tracked_inputs=[
            TrackedInput(
                role="dem",
                category="data",
                path="data/dem/dem.tif",
                declared_path="dem.tif",
                sha256=sha256_of(dem),
                portable=True,
            ),
            TrackedInput(
                role="hydrometry",
                category="data",
                path="data/hydrometry",
                declared_path="hydrometry",
                sha256="f" * 64,
                portable=True,
            ),
        ],
    ).write(run_dir)
    (run_dir / "config.toml").write_text(_CONFIG, encoding="utf-8")
    return publish(
        run_dir,
        tmp_path / "published" / RUN_NAME,
        project_root=project,
        with_=("inputs",),
        inputs=inputs_of(project),
    )


def test_a_declared_file_points_at_its_bytes_and_a_folder_is_rebuilt(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    workdir = tmp_path / "work"

    payload = replay_payload(copy, tomllib.loads(_CONFIG), workdir=workdir)

    (dem_source,) = payload["data"]["dem"]["sources"]
    dem = Path(dem_source["path"])
    assert dem.parent == copy / INPUTS_DIRNAME
    assert dem.read_bytes() == b"the dem bytes"
    (source,) = payload["data"]["hydrometry"]["sources"]
    folder = Path(source["path"])
    assert folder == workdir / "data" / "hydrometry"
    assert sorted(path.name for path in folder.iterdir()) == [
        "hydrometry_custom_LOC.csv",
        CUSTOM_FILE,
    ]
    assert (folder / "hydrometry_custom_LOC.csv").read_text(encoding="utf-8").splitlines() == [
        "id,x,y,crs,unit",
        "NANCON,389285.9,6816518.7,EPSG:2154,m3/s",
    ]
    assert source["station_ids"] == ["NANCON"]
    assert published_copy_of(copy / "config.toml") == copy
    assert published_copy_of(tmp_path / "config.toml") is None


def test_bytes_with_another_digest_or_no_index_refuse_the_replay(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    dem = read_index(copy).file_at("data/dem/dem.tif")
    (copy / INPUTS_DIRNAME / stored_name(dem.sha256, dem.dest)).write_bytes(b"other bytes")

    with pytest.raises(ReplayInputError, match="does not have the digest"):
        replay_payload(copy, tomllib.loads(_CONFIG), workdir=tmp_path / "work")
    (copy / INSTALL_FILENAME).unlink()
    with pytest.raises(ReplayInputError, match="--with inputs"):
        replay_payload(copy, tomllib.loads(_CONFIG), workdir=tmp_path / "work")


def test_a_file_a_provider_delivered_refuses_the_replay_and_names_the_import(
    tmp_path: Path,
) -> None:
    run_dir = make_shared_run(tmp_path / "ws")
    project = run_dir.parent.parent
    copy = publish(
        run_dir,
        tmp_path / "published" / run_dir.name,
        project_root=project,
        with_=("inputs",),
        inputs=inputs_of(project),
    )

    with pytest.raises(ReplayInputError, match="fed by hubeau") as refused:
        replay_payload(copy, {}, workdir=tmp_path / "work")
    assert "hmp catalog import" in str(refused.value)


def test_hmp_run_frozen_on_a_copy_replays_into_the_project_named_by_w(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    before = sorted(path.name for path in copy.iterdir())
    project = tmp_path / "replay"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        ["run", str(copy / "config.toml"), "--frozen", "--dry-run", "-q", "-w", str(project)]
    )

    assert result.exit_code == 0, result.stderr
    assert f"config  : {project / '.hmp' / 'replay' / f'{RUN_NAME}.toml'}" in result.stdout
    assert not (project / ".hmp" / "replay").exists()
    assert sorted(path.name for path in copy.iterdir()) == before


def test_hmp_run_frozen_on_a_copy_without_its_inputs_is_refused(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    (copy / INSTALL_FILENAME).unlink()
    project = tmp_path / "replay"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        ["run", str(copy / "config.toml"), "--frozen", "-q", "-w", str(project)]
    )

    assert result.exit_code == EXIT_CONFIG
    assert "--with inputs" in result.stderr
    assert not (project / "runs").exists()
    assert not (project / ".hmp" / "replay").exists()


def test_two_inputs_of_one_role_keep_their_own_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import hydromodpy.project.exchange.replay as replay
    import hydromodpy.results.manifest as manifest
    import hydromodpy.results.publication as publication

    items = [
        SimpleNamespace(dest=f"data/{name}.tif", sha256=name * 4, root="workspace", provider=None)
        for name in ("a", "b")
    ]
    index = SimpleNamespace(files=items, stations=[])
    entries = [
        {"role": "dem", "path": item.dest, "declared_path": f"{item.dest}"} for item in items
    ]
    monkeypatch.setattr(replay, "checked_index", lambda _copy: index)
    monkeypatch.setattr(replay, "_refuse_delivered_inputs", lambda *_: None)
    monkeypatch.setattr(manifest, "read_manifest", lambda _copy: {"inputs": entries})
    monkeypatch.setattr(
        publication,
        "read_publication",
        lambda _copy: SimpleNamespace(source=SimpleNamespace(project="p")),
    )
    monkeypatch.setattr(replay, "_workspace_path", lambda item, _project: item.dest)
    found = replay.input_files_by_role(tmp_path, tmp_path / "work")
    assert found["data/a.tif"] != found["data/b.tif"]
    assert "dem" not in found
