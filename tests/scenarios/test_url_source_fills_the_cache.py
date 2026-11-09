"""The url and file data sources played on the permanent island.

Three games and two refusals:
1. An island whose recharge comes from a local HTTP server with pinned sha256
   and --allow-host 127.0.0.1. The download fills the project cache and writes its sidecar.
2. The same island replayed with the local server stopped: the cache suffices.
3. The same island played with source = "file" and path = "inputs/r.tif": the
   simulated head fields match the URL run bit for bit.
4. Refusal when dem_init_path is declared, naming its removal message.
5. Refusal when a bare name without folder prefix is declared, naming its message.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import zarr

from tests._helpers.geotiffs import write_geotiff
from tests.scenarios.factory import TRANSIENT
from tests.scenarios.launcher import Scenario, play

MF6_FILES = ("mf6", "libmf6.so")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Simple HTTP request handler that does not log to console."""

    def log_message(self, format: str, *args: object) -> None:
        pass


def _runs_of(played) -> list[Path]:
    """Return the run folders left by a played scenario."""
    return [played.root / path for kind, path in played.targets if kind == "run"]


def _base_island_toml() -> str:
    """Return the baseline MODFLOW 6 transient island TOML."""
    return (
        TRANSIENT.replace("@NAME@", "island")
        .replace("@SOLVER@", "modflow6")
        .replace("@TRANSPORT_PROCESS@", "")
    )


def _url_island_toml(url: str, sha256_digest: str) -> str:
    """Return the island TOML with recharge declared as an URL source."""
    base = _base_island_toml()
    old_data = (
        '[data]\ntypes = ["oceanic"]\n\n[[data.oceanic.sources]]\nsource = "constant"\nvalue = 0.0'
    )
    new_data = f"""\
[data]
types = ["oceanic", "recharge"]

[[data.oceanic.sources]]
source = "constant"
value = 0.0

[[data.recharge.sources]]
source = "url"
url = "{url}"
sha256 = "{sha256_digest}"
"""
    old_rch = "[flow.sinks_sources.recharge]\nvalues = [1.0, 4.0, 2.0]"
    new_rch = "[flow.sinks_sources.recharge]"
    return base.replace(old_data, new_data).replace(old_rch, new_rch)


def _file_island_toml() -> str:
    """Return the island TOML with recharge declared as a file source."""
    base = _base_island_toml()
    old_data = (
        '[data]\ntypes = ["oceanic"]\n\n[[data.oceanic.sources]]\nsource = "constant"\nvalue = 0.0'
    )
    new_data = """\
[data]
types = ["oceanic", "recharge"]

[[data.oceanic.sources]]
source = "constant"
value = 0.0

[[data.recharge.sources]]
source = "file"
path = "inputs/r.tif"
"""
    old_rch = "[flow.sinks_sources.recharge]\nvalues = [1.0, 4.0, 2.0]"
    new_rch = "[flow.sinks_sources.recharge]"
    return base.replace(old_data, new_data).replace(old_rch, new_rch)


def _write_recharge_raster(dest: Path) -> tuple[Path, str]:
    """Write a constant recharge raster matching the 31x31 island grid."""
    data = np.full((31, 31), 2.0, dtype=np.float32)
    path = write_geotiff(
        dest,
        data,
        origin=(0.0, 610.0),
        cell=(610.0 / 31.0, 610.0 / 31.0),
        crs="EPSG:2154",
        nodata=-9999.0,
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def test_url_source_fills_the_cache_and_matches_file_source(
    tmp_path: Path,
    scenario_env: dict[str, str],
    scenario_cache: Path,
) -> None:
    # 1. Create the recharge raster in a local serving folder
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir(parents=True, exist_ok=True)
    tif_path, digest = _write_recharge_raster(serve_dir / "r.tif")
    sha8 = digest[:8]

    # Start the local HTTP server in a thread
    handler = functools.partial(_QuietHandler, directory=str(serve_dir))
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}/r.tif"
    url_toml = _url_island_toml(url, digest)

    try:
        # 2. Run the island with URL source and --allow-host 127.0.0.1
        scenario_url = Scenario(
            name="island_url",
            covers="an island whose recharge is fetched from a local URL source",
            files={"project.toml": url_toml},
            argv=("run", "project.toml", "--allow-host", "127.0.0.1"),
            needs=MF6_FILES,
        )
        played_url = play(scenario_url, tmp_path / "play_url", scenario_env, scenario_cache)
        assert played_url.returncode == 0, played_url.log.read_text(encoding="utf-8")[-2000:]

        # Verify the cached file and its sidecar
        cache_file = played_url.root / "data" / "recharge" / f"recharge_url_127-0-0-1_{sha8}.tif"
        assert cache_file.is_file(), f"missing cache file: {cache_file}"

        sidecar_file = cache_file.with_name(cache_file.name + ".json")
        assert sidecar_file.is_file(), f"missing sidecar file: {sidecar_file}"
        sidecar_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        assert sidecar_data.get("origin") == url
        assert sidecar_data.get("sha256") == digest
    finally:
        # Stop the local server
        server.shutdown()
        server.server_close()
        server_thread.join()

    # 3. Replay the same island project with the server stopped: cache suffices
    replay_cmd = [
        sys.executable,
        "-m",
        "hydromodpy",
        "run",
        "project.toml",
        "--allow-host",
        "127.0.0.1",
    ]
    replayed = subprocess.run(
        replay_cmd,
        cwd=played_url.root,
        env=dict(scenario_env),
        capture_output=True,
        text=True,
    )
    assert replayed.returncode == 0, replayed.stderr or replayed.stdout

    # 4. Play the same island with source = "file" and path = "inputs/r.tif"
    file_toml = _file_island_toml()
    scenario_file = Scenario(
        name="island_file",
        covers="the same island with source = 'file' and path = 'inputs/r.tif'",
        files={"project.toml": file_toml},
        python=(
            f"import shutil, subprocess, sys\n"
            f"from pathlib import Path\n"
            f"Path('inputs').mkdir(parents=True, exist_ok=True)\n"
            f"shutil.copyfile({str(tif_path)!r}, 'inputs/r.tif')\n"
            f"subprocess.run([sys.executable, '-m', 'hydromodpy', 'run', 'project.toml'], check=True)\n"
        ),
        needs=MF6_FILES,
    )
    played_file = play(scenario_file, tmp_path / "play_file", scenario_env, scenario_cache)
    assert played_file.returncode == 0, played_file.log.read_text(encoding="utf-8")[-2000:]

    # Compare the head fields from both runs
    runs_url = _runs_of(played_url)
    runs_file = _runs_of(played_file)
    assert runs_url, "no run found in played_url"
    assert runs_file, "no run found in played_file"

    head_url = np.asarray(zarr.open(str(runs_url[0] / "fields.zarr"), mode="r")["head"][:])
    head_file = np.asarray(zarr.open(str(runs_file[0] / "fields.zarr"), mode="r")["head"][:])

    hash_url = hashlib.sha256(head_url.tobytes()).hexdigest()
    hash_file = hashlib.sha256(head_file.tobytes()).hexdigest()
    assert hash_url == hash_file
    assert np.array_equal(head_url, head_file)


def test_project_with_dem_init_path_is_refused(
    tmp_path: Path,
    scenario_env: dict[str, str],
    scenario_cache: Path,
) -> None:
    base = _base_island_toml()
    dem_toml = base + "\n[geographic.catchment]\ndem_init_path = 'dem.tif'\n"
    scenario_dem = Scenario(
        name="refuse_dem_init_path",
        covers="dem_init_path in TOML is refused with its removal message",
        files={"project.toml": dem_toml},
        argv=("run", "project.toml"),
        needs=(),
    )
    played_dem = play(scenario_dem, tmp_path / "play_dem", scenario_env, scenario_cache)
    assert played_dem.returncode != 0
    log = played_dem.log.read_text(encoding="utf-8")
    assert (
        "geographic.catchment.dem_init_path was removed in 2.1.0" in log
        or "dem_init_path was removed in 2.1.0" in log
    )


def test_project_with_bare_name_path_is_refused(
    tmp_path: Path,
    scenario_env: dict[str, str],
    scenario_cache: Path,
) -> None:
    base = _base_island_toml()
    old_data = (
        '[data]\ntypes = ["oceanic"]\n\n[[data.oceanic.sources]]\nsource = "constant"\nvalue = 0.0'
    )
    bare_data = """\
[data]
types = ["oceanic", "recharge"]

[[data.oceanic.sources]]
source = "constant"
value = 0.0

[[data.recharge.sources]]
source = "file"
path = "DEM_armorican_massif.tif"
"""
    old_rch = "[flow.sinks_sources.recharge]\nvalues = [1.0, 4.0, 2.0]"
    new_rch = "[flow.sinks_sources.recharge]"
    bare_toml = base.replace(old_data, bare_data).replace(old_rch, new_rch)

    scenario_bare = Scenario(
        name="refuse_bare_name",
        covers="a bare name path without inputs/ prefix is refused",
        files={"project.toml": bare_toml},
        argv=("run", "project.toml"),
        needs=(),
    )
    played_bare = play(scenario_bare, tmp_path / "play_bare", scenario_env, scenario_cache)
    assert played_bare.returncode != 0
    log = played_bare.log.read_text(encoding="utf-8")
    assert (
        "is a bare name. HydroModPy no longer looks it up in the workspace data folder" in log
        or "is a bare name" in log
    )
