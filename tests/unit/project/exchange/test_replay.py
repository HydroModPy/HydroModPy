"""Replay of a published copy from the bytes the copy carries.

``hmp replay <copy> -w <project>`` checks every file of the install index
against ``inputs/`` and points each recorded role at those bytes. A missing
file or a wrong digest refuses the replay before anything runs. The full chain,
a solve included, is ``tests/e2e/test_replay_from_archive_without_workspace.py``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG
from hydromodpy.core.payload.index import INSTALL_FILENAME, read_index, stored_name
from hydromodpy.core.payload.install import PayloadConflictError
from hydromodpy.project.exchange.replay import (
    ReplayInputError,
    published_copy_of,
    replay_payload,
)
from hydromodpy.project.exchange.share import inputs_of
from hydromodpy.results.export.publish import INPUTS_DIRNAME, publish
from hydromodpy.results.record.manifest import InputEntry, TrackedInput
from tests._helpers.cli_runner import CliRunner
from tests._helpers.run_records import make_record
from tests.unit.catalog._shared_run import (
    CUSTOM_FILE,
    CUSTOM_LOC,
    HUBEAU_FILE,
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


def test_payload_points_at_copy_bytes(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    workdir = tmp_path / "work"

    payload = replay_payload(copy, tomllib.loads(_CONFIG), workdir=workdir, project_root=tmp_path)

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


def test_bad_digest_or_no_index_refused(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    dem = read_index(copy).file_at("data/dem/dem.tif")
    (copy / INPUTS_DIRNAME / stored_name(dem.sha256, dem.dest)).write_bytes(b"other bytes")

    with pytest.raises(ReplayInputError, match="does not have the digest"):
        replay_payload(
            copy, tomllib.loads(_CONFIG), workdir=tmp_path / "work", project_root=tmp_path
        )
    (copy / INSTALL_FILENAME).unlink()
    with pytest.raises(ReplayInputError, match="published with --without inputs"):
        replay_payload(
            copy, tomllib.loads(_CONFIG), workdir=tmp_path / "work", project_root=tmp_path
        )


def _published_with_a_delivered_file(tmp_path: Path) -> Path:
    run_dir = make_shared_run(tmp_path / "ws")
    project = run_dir.parent.parent
    return publish(
        run_dir,
        tmp_path / "published" / run_dir.name,
        project_root=project,
        with_=("inputs",),
        inputs=inputs_of(project),
    )


def test_delivered_file_installed_by_digest(tmp_path: Path) -> None:
    copy = _published_with_a_delivered_file(tmp_path)
    project = make_workspace(tmp_path / "colleague", project="lab")
    delivered = read_index(copy).file_at(f"data/hydrometry/{HUBEAU_FILE}")

    replay_payload(copy, {}, workdir=tmp_path / "work", project_root=project)

    installed = tmp_path / "colleague" / delivered.dest
    assert sha256_of(installed) == delivered.sha256
    assert installed.with_name(installed.name + ".json").is_file()
    assert (installed.parent / "hydrometry_hubeau_LOC.csv").is_file()
    assert not (tmp_path / "colleague" / "data" / "dem").exists()
    assert not (installed.parent / CUSTOM_FILE).exists()


def test_delivered_file_conflict_refused(
    tmp_path: Path,
) -> None:
    copy = _published_with_a_delivered_file(tmp_path)
    project = make_workspace(tmp_path / "colleague", project="lab")
    held = tmp_path / "colleague" / "data" / "hydrometry" / HUBEAU_FILE
    held.parent.mkdir(parents=True)
    held.write_text("other bytes\n", encoding="utf-8")

    with pytest.raises(PayloadConflictError, match=HUBEAU_FILE):
        replay_payload(copy, {}, workdir=tmp_path / "work", project_root=project)

    assert held.read_text(encoding="utf-8") == "other bytes\n"
    assert sorted(path.name for path in held.parent.iterdir()) == [HUBEAU_FILE]


def test_run_frozen_names_replay_verb(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    before = sorted(path.name for path in copy.iterdir())
    project = tmp_path / "replay"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        ["run", str(copy / "config.toml"), "--frozen", "-q", "-w", str(project)]
    )

    assert result.exit_code == EXIT_CONFIG
    assert "hmp replay" in result.stderr
    assert not (project / "runs").exists()
    assert sorted(path.name for path in copy.iterdir()) == before


def test_replay_without_inputs_refused(tmp_path: Path) -> None:
    copy = _published(tmp_path)
    (copy / INSTALL_FILENAME).unlink()
    project = tmp_path / "replay"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")

    result = CliRunner().invoke(["replay", str(copy), "-q", "-w", str(project)])

    assert result.exit_code == EXIT_CONFIG
    assert "published with --without inputs" in result.stderr
    assert not (project / "runs").exists()
    assert not (project / ".hmp" / "replay").exists()


def test_inputs_of_one_role_stay_apart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import hydromodpy.project.exchange.replay as replay
    import hydromodpy.results.publication as publication
    import hydromodpy.results.record.manifest as manifest

    items = [
        SimpleNamespace(dest=f"data/{name}.tif", sha256=name * 4, root="workspace", provider=None)
        for name in ("a", "b")
    ]
    index = SimpleNamespace(files=items, stations=[])
    entries = [
        {"role": "dem", "path": item.dest, "declared_path": f"{item.dest}"} for item in items
    ]
    monkeypatch.setattr(replay, "checked_index", lambda _copy: index)
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


def test_folder_copied_when_link_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = _published(tmp_path)
    linked = tmp_path / "linked"
    payload = replay_payload(copy, tomllib.loads(_CONFIG), workdir=linked, project_root=tmp_path)
    expected = {
        path.name: path.read_bytes()
        for path in Path(payload["data"]["hydrometry"]["sources"][0]["path"]).iterdir()
    }

    def refused(source: object, target: object) -> None:
        raise PermissionError("no hard link here")

    monkeypatch.setattr(os, "link", refused)
    copied = tmp_path / "copied"
    payload = replay_payload(copy, tomllib.loads(_CONFIG), workdir=copied, project_root=tmp_path)

    folder = Path(payload["data"]["hydrometry"]["sources"][0]["path"])
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == expected


_KILLED_REPLAY = """\
import os, signal, sys, tomllib
from pathlib import Path
from hydromodpy.project import replay
from hydromodpy.project.exchange.replay import replay_payload

def build_then_die(*args, **kwargs):
    replay_payload(*args, **kwargs)
    os.kill(os.getpid(), signal.SIGKILL)

replay._play_copy(
    Path(sys.argv[1]), tomllib.loads(sys.argv[3]), project_root=Path(sys.argv[2]),
    environment=None, strict=False, payload=build_then_die,
)
"""


@pytest.mark.allow_subprocess
@pytest.mark.skipif(os.name == "nt", reason="SIGKILL is POSIX")
def test_killed_replay_does_not_block_next(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import signal
    import subprocess
    import sys

    import hydromodpy.project.dispatch.workflow as workflow
    import hydromodpy.project.request as request
    from hydromodpy.project import replay

    copy = _published(tmp_path)
    project = tmp_path / "replay"
    project.mkdir()
    root = Path(__file__).resolve().parents[4]
    killed = subprocess.run(
        [sys.executable, "-c", _KILLED_REPLAY, str(copy), str(project), _CONFIG],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        check=False,
    )
    assert killed.returncode == -signal.SIGKILL, killed.stderr.decode()[-2000:]
    left = project / ".hmp" / "replay" / copy.name
    assert (left / "data" / "hydrometry" / CUSTOM_FILE).is_file()

    played: list[object] = []
    monkeypatch.setattr(request, "RunRequest", lambda **kwargs: kwargs)
    monkeypatch.setattr(workflow, "run_simulation", lambda req, **kwargs: played.append(req))
    replay._play_copy(
        copy,
        tomllib.loads(_CONFIG),
        project_root=project,
        environment=None,
        strict=False,
        payload=replay_payload,
    )

    assert len(played) == 1
    assert not (project / ".hmp" / "replay").exists()
