"""The frozen configuration of a published copy replays from the bytes the copy carries.

``hmp run <copy>/config.toml --frozen`` checks every input the seal records
against ``inputs/<sha256><suffix>`` and points the field of that role at those
bytes; a missing input, or bytes with another digest, refuse the replay before
anything runs. The run goes to the project ``-w`` names. The full chain, a
solve included, is ``tests/e2e/test_replay_from_archive_without_workspace.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.project.launch.replay import (
    ReplayInputError,
    published_copy_of,
    replay_payload,
)
from hydromodpy.results.manifest import RUN_RECORD_MANIFEST_VERSION
from tests._helpers.cli_runner import CliRunner

_CONFIG = """\
[workflow]
mode = "simulation"

[simulation]
name = "nancon_step1_minimal"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "<absolute path>"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"
"""


def _copy(tmp_path: Path, *, dem: bytes = b"the dem bytes", store: bool = True) -> Path:
    copy = tmp_path / "published" / "nancon_step1_minimal"
    copy.mkdir(parents=True)
    sha256 = hashlib.sha256(b"the dem bytes").hexdigest()
    (copy / "config.toml").write_text(_CONFIG, encoding="utf-8")
    (copy / "PUBLICATION.json").write_text("{}", encoding="utf-8")
    (copy / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": RUN_RECORD_MANIFEST_VERSION,
                "inputs": [
                    {
                        "role": "dem",
                        "category": "data",
                        "path": "<absolute path>",
                        "declared_path": "<absolute path>",
                        "sha256": sha256,
                        "portable": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    if store:
        (copy / "inputs").mkdir()
        (copy / "inputs" / f"{sha256}.tif").write_bytes(dem)
    return copy


def test_each_recorded_input_points_at_the_bytes_of_the_copy(tmp_path: Path) -> None:
    import tomllib

    copy = _copy(tmp_path)

    payload = replay_payload(copy, tomllib.loads(_CONFIG))

    dem = Path(payload["geographic"]["catchment"]["dem_init_path"])
    assert dem.parent == copy / "inputs"
    assert dem.read_bytes() == b"the dem bytes"
    assert published_copy_of(copy / "config.toml") == copy
    assert published_copy_of(tmp_path / "config.toml") is None


def test_bytes_with_another_digest_or_no_bytes_refuse_the_replay(tmp_path: Path) -> None:
    import tomllib

    tampered = _copy(tmp_path / "a", dem=b"other bytes")
    missing = _copy(tmp_path / "b", store=False)

    with pytest.raises(ReplayInputError, match="does not have the digest"):
        replay_payload(tampered, tomllib.loads(_CONFIG))
    with pytest.raises(ReplayInputError, match="--with inputs"):
        replay_payload(missing, tomllib.loads(_CONFIG))


def test_hmp_run_frozen_on_a_copy_replays_into_the_project_named_by_w(tmp_path: Path) -> None:
    copy = _copy(tmp_path)
    project = tmp_path / "replay"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        ["run", str(copy / "config.toml"), "--frozen", "--dry-run", "-q", "-w", str(project)]
    )

    assert result.exit_code == 0, result.stderr
    assert f"config  : {project / '.hmp' / 'replay' / 'nancon_step1_minimal.toml'}" in (
        result.stdout
    )
    assert not (project / ".hmp" / "replay").exists()
    assert sorted(path.name for path in copy.iterdir()) == [
        "PUBLICATION.json",
        "config.toml",
        "inputs",
        "manifest.json",
    ]


def test_hmp_run_frozen_on_a_copy_without_its_inputs_is_refused(tmp_path: Path) -> None:
    copy = _copy(tmp_path, store=False)
    project = tmp_path / "replay"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        ["run", str(copy / "config.toml"), "--frozen", "-q", "-w", str(project)]
    )

    assert result.exit_code == EXIT_CONFIG
    assert "--with inputs" in result.stderr
    assert not (project / "runs").exists()


_FOLDER_CONFIG = """\
[data]
types = ["hydrometry"]

[[data.hydrometry.sources]]
source = "custom"
path = "<absolute path>"
station_ids = ["NANCON"]
"""


def _folder_copy(tmp_path: Path, *, provider: str = "custom") -> tuple[Path, str]:
    """A copy whose seal declares a folder of station files, loaded by ``provider``."""
    from hydromodpy.results.storage.digests import sha256_directory

    folder = tmp_path / "data" / "hydrometry"
    folder.mkdir(parents=True)
    station = folder / "hydrometry_custom_NANCON_20000101_20001231_D.csv"
    station.write_text("datetime,value\n2000-01-01,1.0\n", encoding="utf-8")
    (folder / f"{station.name}.json").write_text('{"source": "custom"}', encoding="utf-8")
    sha256 = sha256_directory(folder)
    copy = tmp_path / "published" / "nancon_step5_export"
    copy.mkdir(parents=True)
    (copy / "config.toml").write_text(_FOLDER_CONFIG, encoding="utf-8")
    (copy / "PUBLICATION.json").write_text("{}", encoding="utf-8")
    (copy / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": RUN_RECORD_MANIFEST_VERSION,
                "inputs": [
                    {
                        "role": "hydrometry",
                        "category": "data",
                        "path": "<absolute path>",
                        "declared_path": "<absolute path>",
                        "sha256": sha256,
                        "portable": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (copy / "inputs.json").write_text(
        json.dumps(
            {
                "schema": "hydromodpy.inputs.v1",
                "sim_id": "5ac4a80e-4674-4edc-9289-16abf79acb75",
                "inputs": [
                    {
                        "variable": "hydrometry:discharge",
                        "provider": provider,
                        "request": {"station": "NANCON"},
                        "path": "<absolute path>",
                        "sha256": hashlib.sha256(station.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (copy / "inputs").mkdir()
    import shutil

    shutil.copytree(folder, copy / "inputs" / sha256)
    return copy, sha256


def test_a_declared_folder_in_a_list_of_sources_points_at_its_copy(tmp_path: Path) -> None:
    import tomllib

    copy, sha256 = _folder_copy(tmp_path)

    payload = replay_payload(copy, tomllib.loads(_FOLDER_CONFIG))

    (source,) = payload["data"]["hydrometry"]["sources"]
    assert Path(source["path"]) == copy / "inputs" / sha256
    assert source["station_ids"] == ["NANCON"]


def test_an_input_a_provider_delivered_refuses_the_frozen_replay(tmp_path: Path) -> None:
    import tomllib

    copy, _ = _folder_copy(tmp_path, provider="hubeau")

    with pytest.raises(ReplayInputError, match="fed by hubeau"):
        replay_payload(copy, tomllib.loads(_FOLDER_CONFIG))
