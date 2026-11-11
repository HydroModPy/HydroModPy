"""The export files of a sealed run are delivered to a folder and to an FTP server.

One transient island, played in three projects:
1. ``hmp run island.toml --credentials ... --allow-host 127.0.0.1`` delivers
   ``head_last.tif`` to a local folder and to the test FTP server.
2. A second project whose server refuses three ``STOR``: the run is sealed,
   the ftp line is failed after three attempts, and ``hmp export island
   --deliver`` sends that file again.
3. A server that answers nothing: exit 16 before any computation, no ``runs/``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from hydromodpy.results.publication import read_published
from tests._helpers.ftp_server import ftp_server
from tests.scenarios.factory import TRANSIENT
from tests.scenarios.launcher import Scenario, play

EXPORT_BLOCK = """\

[[export]]
variables = "head"
time = "last"
file = "head_last.tif"
crs = "EPSG:2154"
deliver_to = @DESTINATIONS@
"""
FILE_NAME = "head_last.tif"
WARNING = "could not deliver"


def _island_toml(name: str, destinations: list[str]) -> str:
    """Return the transient MODFLOW 6 island, named *name*, with its export block."""
    text = (
        TRANSIENT.replace("@NAME@", name)
        .replace("@SOLVER@", "modflow6")
        .replace("@TRANSPORT_PROCESS@", "")
    )
    return text + EXPORT_BLOCK.replace("@DESTINATIONS@", json.dumps(destinations))


def _credentials(path: Path, prefix: str) -> Path:
    """Write one ``[[host]]`` block for *prefix*, readable by its owner only."""
    path.write_text(
        f'[[host]]\nprefix = {json.dumps(prefix)}\nuser = "user"\npassword = "secret"\n',
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return path


def _hmp(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* with the environment of the scenario."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *args],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _delivery_lines(run_dir: Path) -> list:
    return [line for line in read_published(run_dir) if line.kind == "delivery"]


def _states(lines: list) -> list[str]:
    return [line.state for line in lines]


def _of(lines: list, prefix: str) -> list:
    return [line for line in lines if (line.destination or "").startswith(prefix)]


def _no_parts(root: Path) -> None:
    assert list(root.rglob("*.part")) == []


def _dead_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_exports_are_delivered(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    # 1. The run delivers to the folder and to the server.
    depot = tmp_path / "depot"
    depot.mkdir()
    server_root = tmp_path / "server-one"
    (server_root / "depot").mkdir(parents=True)
    with ftp_server(server_root) as port:
        address = f"ftp://127.0.0.1:{port}/depot/"
        credentials = _credentials(tmp_path / "credentials-one.toml", address)
        scenario = Scenario(
            name="delivered",
            covers="delivery of the export files to a folder and to an FTP server",
            files={
                "island.toml": _island_toml("island", [str(depot) + "/", address]),
            },
            argv=(
                "run",
                "island.toml",
                "--credentials",
                str(credentials),
                "--allow-host",
                "127.0.0.1",
            ),
        )
        played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
        assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-3000:]
        run_dir = played.root / "runs" / "island"
        assert played.targets == (("run", "runs/island"),)
        exported = (run_dir / "exports" / FILE_NAME).read_bytes()
        assert (depot / FILE_NAME).read_bytes() == exported
        assert (server_root / "depot" / FILE_NAME).read_bytes() == exported
        _no_parts(depot)
        _no_parts(server_root)
        lines = _delivery_lines(run_dir)
        assert _states(lines) == ["pending", "delivered", "pending", "delivered"]
        assert len(_of(lines, str(depot))) == 2
        assert len(_of(lines, address)) == 2

    # 2. Three refused STOR leave the ftp line failed; the export sends it again.
    depot_two = tmp_path / "depot-two"
    depot_two.mkdir()
    server_two = tmp_path / "server-two"
    (server_two / "depot").mkdir(parents=True)
    with ftp_server(server_two, fail_stor=3) as port:
        address = f"ftp://127.0.0.1:{port}/depot/"
        credentials = _credentials(tmp_path / "credentials-two.toml", address)
        scenario = Scenario(
            name="delivered-again",
            covers="a refused delivery, its failed line and its later push",
            files={
                "island.toml": _island_toml("island", [str(depot_two) + "/", address]),
            },
            argv=(
                "run",
                "island.toml",
                "--credentials",
                str(credentials),
                "--allow-host",
                "127.0.0.1",
            ),
        )
        played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
        assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-3000:]
        assert WARNING in played.log.read_text(encoding="utf-8")
        root = played.root
        run_dir = root / "runs" / "island"
        assert (run_dir / "manifest.json").is_file()
        lines = _delivery_lines(run_dir)
        local = _of(lines, str(depot_two))
        remote = _of(lines, address)
        assert _states(local) == ["pending", "delivered"]
        assert _states(remote) == ["pending", "failed"]
        assert remote[-1].attempts == 3
        assert remote[-1].error
        _no_parts(depot_two)
        _no_parts(server_two)

        again = _hmp(
            root,
            scenario_env,
            "export",
            "island",
            "--deliver",
            "--credentials",
            str(credentials),
            "--allow-host",
            "127.0.0.1",
        )
        assert again.returncode == 0, again.stderr[-3000:]
        assert "Delivered 1 of 1 file(s)" in again.stderr
        lines = _delivery_lines(run_dir)
        assert _states(_of(lines, str(depot_two))) == ["pending", "delivered"]
        assert _states(_of(lines, address)) == ["pending", "failed", "pending", "delivered"]
        exported = (run_dir / "exports" / FILE_NAME).read_bytes()
        assert (server_two / "depot" / FILE_NAME).read_bytes() == exported
        _no_parts(server_two)

    # 3. A server that answers nothing stops the run before it claims a folder.
    port = _dead_port()
    address = f"ftp://127.0.0.1:{port}/depot/"
    credentials = _credentials(tmp_path / "credentials-three.toml", address)
    scenario = Scenario(
        name="undeliverable",
        covers="a checked destination that answers nothing, before any computation",
        files={"island.toml": _island_toml("island", [address])},
        argv=(
            "run",
            "island.toml",
            "--credentials",
            str(credentials),
            "--allow-host",
            "127.0.0.1",
        ),
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 16, played.log.read_text(encoding="utf-8")[-3000:]
    assert not (played.root / "runs").exists()
