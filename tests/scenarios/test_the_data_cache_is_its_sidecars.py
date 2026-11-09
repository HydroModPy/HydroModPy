"""The data cache of the island is its sidecars, and nothing else.

One island reads its recharge from a local HTTP server. The scenario plays it and
checks, in order:
1. The run leaves no ``cache.duckdb`` and a sidecar that holds variable, source,
   origin, digest, size and licence. ``hmp data ls`` lists the row.
2. ``hmp data lock`` writes a v2 lockfile with the licence, and ``--check`` passes.
3. A ``--frozen`` replay with the server stopped passes. After the file changes,
   the same replay and ``--check`` refuse it, and the file comes back.
4. ``hmp data prune`` removes a fetched file that nothing cites, keeps the cited
   file and names it.
5. A copy of the island of the 2.0.0 corpus is refused by the scan, then read once
   its database is gone, and its v1 lockfile is refused with the new command.
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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import DataCacheError, SchemaVersionMismatchError
from hydromodpy.data.provenance.lockfile import read_lockfile_inputs, read_lockfile_meta
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    Sidecar,
    scan,
    write_sidecar,
)
from tests._helpers.geotiffs import write_geotiff
from tests.scenarios.factory import TRANSIENT
from tests.scenarios.launcher import Scenario, play

MF6_FILES = ("mf6", "libmf6.so")
LICENCE = "CC-BY-4.0"
CORPUS_ISLAND = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "frozen_documents"
    / "v2.0.0"
    / "current"
    / "island"
)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """A file server that logs nothing."""

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def _serve(folder: Path) -> Iterator[int]:
    """Serve *folder* on 127.0.0.1 in a thread and yield the port."""
    handler = functools.partial(_QuietHandler, directory=str(folder))
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _island_toml(url: str, digest: str) -> str:
    """Return the island whose recharge is the file at *url*, pinned by *digest*."""
    base = TRANSIENT.replace("@NAME@", "island").replace("@SOLVER@", "modflow6")
    base = base.replace("@TRANSPORT_PROCESS@", "")
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
sha256 = "{digest}"
license = "{LICENCE}"
"""
    old_rch = "[flow.sinks_sources.recharge]\nvalues = [1.0, 4.0, 2.0]"
    return base.replace(old_data, new_data).replace(old_rch, "[flow.sinks_sources.recharge]")


def _hmp(root: Path, env: Mapping[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* and return the finished process."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )


def _said(done: subprocess.CompletedProcess[str]) -> str:
    return f"{done.stdout}\n{done.stderr}"


def test_the_data_cache_is_its_sidecars(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    raster = write_geotiff(
        serve_dir / "r.tif",
        np.full((31, 31), 2.0, dtype=np.float32),
        origin=(0.0, 610.0),
        cell=(610.0 / 31.0, 610.0 / 31.0),
        crs="EPSG:2154",
        nodata=-9999.0,
    )
    digest = hashlib.sha256(raster.read_bytes()).hexdigest()

    # 1. The run fills the cache of the project, with no database.
    with _serve(serve_dir) as port:
        url = f"http://127.0.0.1:{port}/r.tif"
        played = play(
            Scenario(
                name="island",
                covers="the data cache of the island is its sidecars and no database",
                files={"project.toml": _island_toml(url, digest)},
                argv=("run", "project.toml", "--allow-host", "127.0.0.1"),
                needs=MF6_FILES,
            ),
            tmp_path / "play",
            scenario_env,
            scenario_cache,
        )
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    root = played.root
    data = root / "data"
    assert not list(root.rglob(FORMER_CACHE_DATABASE)), "a run wrote cache.duckdb"
    assert not list(data.rglob("*.duckdb"))

    cached = data / "recharge" / f"recharge_url_127-0-0-1_{digest[:8]}.tif"
    assert cached.is_file()
    sidecar = json.loads(cached.with_name(cached.name + ".json").read_text(encoding="utf-8"))
    assert sidecar["variable"] == "recharge"
    assert sidecar["source"] == "url"
    assert sidecar["origin"] == url
    assert sidecar["sha256"] == digest
    assert sidecar["bytes"] == cached.stat().st_size
    assert sidecar["license"] == LICENCE
    # A url source never opens the file, so it writes no extent and no period it did not read.
    # The writer keeps ``bbox`` and ``crs`` as null keys, so their bytes never move.
    assert sidecar["bbox"] is None and sidecar["crs"] is None
    assert "date_start" not in sidecar and "date_end" not in sidecar

    report = scan(data)
    assert [(row.variable, row.source, row.sha256) for row in report.rows] == [
        ("recharge", "url", digest)
    ]
    listed = _hmp(root, scenario_env, "data", "ls", "-w", str(root))
    assert listed.returncode == 0, _said(listed)
    assert "recharge" in listed.stdout and "url" in listed.stdout

    # 2. The lockfile is read from the sidecars, with the licence.
    locked = _hmp(root, scenario_env, "data", "lock", "--project", ".")
    assert locked.returncode == 0, _said(locked)
    lockfile = root / "hydromodpy.lock"
    text = lockfile.read_text(encoding="utf-8")
    assert 'schema = "hydromodpy.lock.v2"' in text
    assert "file_mtime" not in text and "[binaries]" not in text
    inputs = read_lockfile_inputs(lockfile)
    assert [(i.variable, i.source, i.sha256, i.license) for i in inputs] == [
        ("recharge", "url", digest, LICENCE)
    ]
    assert read_lockfile_meta(lockfile)["hydromodpy_version"]
    checked = _hmp(root, scenario_env, "data", "lock", "--check", "--project", ".")
    assert checked.returncode == 0, _said(checked)

    # 3. The server is gone. A frozen replay reads the cache, a changed file is refused.
    frozen = ("run", "project.toml", "--allow-host", "127.0.0.1", "--frozen")
    replayed = _hmp(root, scenario_env, *frozen)
    assert replayed.returncode == 0, _said(replayed)[-2000:]
    original = cached.read_bytes()
    cached.write_bytes(original + b"\0")
    refused = _hmp(root, scenario_env, *frozen)
    assert refused.returncode != 0
    assert "mismatch" in _said(refused).lower()
    assert cached.name in _said(refused)
    drifted = _hmp(root, scenario_env, "data", "lock", "--check", "--project", ".")
    assert drifted.returncode != 0
    cached.write_bytes(original)
    assert _hmp(root, scenario_env, "data", "lock", "--check", "--project", ".").returncode == 0

    # 4. Prune removes the fetched file nothing cites and names the one a run cites.
    stray = data / "recharge" / "recharge_url_127-0-0-1_stray.tif"
    stray.write_bytes(b"fetched once, cited by nobody")
    write_sidecar(
        stray,
        Sidecar(
            source="url",
            variable="recharge",
            origin=f"{url}.stray",
            sha256=hashlib.sha256(stray.read_bytes()).hexdigest(),
            bytes=stray.stat().st_size,
            fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
            license=LICENCE,
        ),
    )
    stray_sidecar = stray.with_name(stray.name + ".json")
    dry = _hmp(
        root, scenario_env, "data", "prune", "-w", str(root), "--older-than", "0", "--dry-run"
    )
    assert dry.returncode == 0, _said(dry)
    assert stray.is_file() and stray_sidecar.is_file()
    pruned = _hmp(
        root,
        scenario_env,
        "data",
        "prune",
        "-w",
        str(root),
        "--older-than",
        "0",
        "--delete-files",
        "-y",
    )
    assert pruned.returncode == 0, _said(pruned)
    assert not stray.exists() and not stray_sidecar.exists()
    assert cached.is_file() and cached.with_name(cached.name + ".json").is_file()
    assert cached.name in _said(pruned)
    assert [row.sha256 for row in scan(data).rows] == [digest]


def test_the_island_of_the_2_0_0_corpus_is_refused(tmp_path: Path) -> None:
    island = tmp_path / "island"
    shutil.copytree(CORPUS_ISLAND, island)
    database = island / "data" / FORMER_CACHE_DATABASE
    assert database.is_file()

    with pytest.raises(DataCacheError) as refusal:
        scan(island / "data")
    said = str(refusal.value)
    assert FORMER_CACHE_DATABASE in said
    assert "hmp workspace clean --data-cache" in said
    assert database.is_file(), "the refusal must not repair or move the database"

    # Without the database the sidecars speak for themselves. The file of the user
    # is no row, and a sidecar the 2.0.0 wrote without its variable is named.
    for stale in database.parent.glob(f"{FORMER_CACHE_DATABASE}*"):
        stale.unlink()
    report = scan(island / "data")
    assert [(row.variable, row.source) for row in report.rows] == [("piezometry", "hubeau")]
    assert [path.name for path in report.user_files] == ["piezometry_custom_W1_D.csv"]
    assert [path.name for path in report.without_variable] == ["dem_ign.tif.json"]
    assert report.unreadable == ()

    with pytest.raises(SchemaVersionMismatchError) as old_lock:
        read_lockfile_inputs(island / "hydromodpy.lock")
    assert "hydromodpy.lock.v1" in str(old_lock.value)
    assert "hmp data lock" in str(old_lock.value)
