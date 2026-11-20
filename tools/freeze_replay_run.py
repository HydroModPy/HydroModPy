"""Write the frozen MODFLOW 6 run that ``tests/regression/frozen_replay/`` replays.

Write it again when the version moves, with one command::

    python -m tools.freeze_replay_run --out tests/regression/frozen_replay/v2.0.0 --work <folder>

It runs the transient island on 434 gmsh triangles with MODFLOW 6, XT3D off, through
the same ``hmp run`` a user types, in a throwaway project under ``--work``. It then
writes under ``--out``:

- ``current/``, the file ``tri.toml`` and the run ``runs/tri/`` as the code stored them;
- ``expected.json``, the size, the digest of ``current/`` and the digests of the values
  the seal holds.

The host, the user and the local folders are replaced in every file, and the digests of
the sealed files are written again, so the seal stays true. The ids and the dates of the
run are kept: a replay of the copy must still find its own sim id.

Run it under the lock of the real runs, since it solves one model. Nothing runs this at
test time: the test only reads what this wrote.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import platformdirs

from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.core.io.filesystem import link_or_copy
from hydromodpy.results.record.manifest import seal_problems

ROOT = Path(__file__).resolve().parents[1]
RUN = "tri"
NEUTRAL_NAME = "frozen"
BIN_TAG = "<HMP_BIN>"
WORK_TAG = "<work>"
HOME_TAG = "~"
TIMEOUT_S = 900

TRI_TOML = """\
[workflow]
mode = "simulation"

[site]
name = "island"

[workspace]

[simulation]
name = "tri"

[simulation.results]
keep_solver_files = false

[simulation.results.persistence]
field_precision = "exact"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[display]
enabled = false

[simulation.time]
start_datetime = "2003-01-01"
end_datetime = "2003-03-31"
step_value = "1 month"
coverage_policy = "ignore"

[geographic]
source_mode = "synthetic"

[geographic.synthetic]
case_id = "island"

[geographic.synthetic.grid]
length_x = "610.0 m"
length_y = "610.0 m"
nx = 31
ny = 31

[geographic.synthetic.topography]
kind = "radial_island"
base_elevation = -1.0
crest_elevation = 12.0
island_radius = "200.0 m"

[domain.depth_model]
kind = "flat_substratum"
substratum_elevation = -5.0

[data]
types = ["oceanic"]

[[data.oceanic.sources]]
source = "constant"
value = 0.0


[flow]
flow_regime = "transient"
first_period_steady = true
param_list = ["K", "Sy", "Ss"]

[flow.param.K.field]
kind = "homogeneous"
value = "5e-6 m/s"

[flow.bc.ocean]
kind = "dirichlet"
value = "0.0 m"

[flow.bc.drainage]

[flow.sinks_sources.recharge]
values = [1.0, 4.0, 2.0]

[domain.layers]
nlay = 1

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5

[mesh]
engine = "triangle"
cell_size = 30.0

[solver.modflow6.runtime]
mf6_enable_xt3d = false
"""

MACHINE_KEYS = frozenset({"hostname", "user", "host"})
"""Keys of a run document that name the machine or the person that wrote it."""

NEUTRALISED = ("provenance.json", "outcome.json", "logs/heartbeat.json", "logs/run.log")
"""Files of the run that name the machine, as the run writes them."""

THREAD_PINS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "RAYON_NUM_THREADS": "1",
}


def main(argv: list[str] | None = None) -> None:
    """Solve the island, neutralise the machine, check the seal and write both outputs."""
    args = _parse(argv)
    out, work = args.out.resolve(), args.work.resolve()
    _require_empty(
        out,
        f"{out} already holds a frozen run: remove it first, then write it again from the version that tags",
    )
    _require_empty(work, f"{work} is not empty: give --work a new folder")
    machine_bin = _machine_bin_dir(args.bin_dir)
    home = Path.home()

    project = work / "project"
    _solve(work, project, machine_bin)
    run_dir = project / "runs" / RUN
    _neutralise(run_dir, (work / "cache" / "bin", work, home))
    _refresh_the_certified_digests(run_dir)
    problems = seal_problems(run_dir)
    if problems:
        raise SystemExit(
            "the seal no longer holds after the names were replaced: " + "; ".join(problems)
        )
    _check_no_name_left(project, home)

    current = out / "current"
    current.mkdir(parents=True)
    shutil.copy2(project / "tri.toml", current / "tri.toml")
    shutil.copytree(run_dir, current / "runs" / RUN)
    expected = _expected(current)
    (out / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(f"{current}: {expected['bytes'] / 1000:.0f} kB, {expected['cells']} cells")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tools.freeze_replay_run", description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="folder that receives the run")
    parser.add_argument(
        "--work", type=Path, required=True, help="new folder for the solve, never /tmp"
    )
    parser.add_argument("--bin-dir", type=Path, default=None, help="folder that holds mf6")
    return parser.parse_args(argv)


def _require_empty(folder: Path, message: str) -> None:
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(message)


def _machine_bin_dir(given: Path | None) -> Path:
    """Return the folder that holds ``mf6``, read before the environment is isolated."""
    if given is not None:
        folder = given.expanduser().resolve()
    elif os.environ.get("HMP_BIN"):
        folder = Path(os.environ["HMP_BIN"]).expanduser().resolve()
    else:
        folder = Path(platformdirs.user_cache_dir("hydromodpy")) / "bin"
    if not (folder / "mf6").is_file():
        raise SystemExit(f"mf6 is not installed in {folder}: install it, or give --bin-dir")
    return folder


# --------------------------------------------------------------------------- the solve


def _solve(work: Path, project: Path, machine_bin: Path) -> None:
    """Write ``tri.toml`` and play it with ``python -m hydromodpy run``."""
    cache = work / "cache"
    (cache / "bin").mkdir(parents=True)
    for name in ("mf6", ".manifest.json"):
        if (machine_bin / name).is_file():
            link_or_copy(machine_bin / name, cache / "bin" / name)
    project.mkdir(parents=True)
    (project / "tri.toml").write_bytes(TRI_TOML.encode("utf-8"))
    done = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "run", "tri.toml"],
        cwd=project,
        env=_environment(work, cache),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(f"hmp run failed with {done.returncode}:\n{done.stderr[-2000:]}")


def _environment(work: Path, cache: Path) -> dict[str, str]:
    """Return the environment of the solve: a home, a state and a cache of its own."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HMP_", "XDG_"))
        and key not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "MPLCONFIGDIR")
    }
    for name in ("home", "state", "tmp"):
        (work / name).mkdir(exist_ok=True)
    env.update(
        HOME=str(work / "home"),
        HMP_CACHE_HOME=str(cache),
        HMP_STATE_HOME=str(work / "state"),
        TMPDIR=str(work / "tmp"),
        PYTHONPATH=str(ROOT),
        PYTHONHASHSEED="42",
        MPLBACKEND="Agg",
        HMP_NO_PROGRESS="1",
        HMP_DETERMINISTIC_FETCHED_AT="1",
        TZ="UTC",
        **THREAD_PINS,
    )
    if os.name == "posix":
        env["LC_ALL"] = "C.UTF-8"
    return env


# --------------------------------------------------------------------------- the names


def _neutralise(run_dir: Path, folders: tuple[Path, Path, Path]) -> None:
    """Replace the host, the user and the local folders in the files that name them."""
    binaries, work, home = (str(folder) for folder in folders)
    swaps = ((binaries, BIN_TAG), (work, WORK_TAG), (home, HOME_TAG))
    for relative in NEUTRALISED:
        path = run_dir / relative
        if not path.is_file():
            continue
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(_neutral(payload, swaps), indent=2, ensure_ascii=False) + "\n"
        else:
            text = _swapped(path.read_text(encoding="utf-8"), swaps)
        path.write_text(text, encoding="utf-8", newline="\n")


def _neutral(value: Any, swaps: tuple[tuple[str, str], ...]) -> Any:
    if isinstance(value, dict):
        return {
            key: NEUTRAL_NAME if key in MACHINE_KEYS else _neutral(item, swaps)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_neutral(item, swaps) for item in value]
    if isinstance(value, str):
        return _swapped(value, swaps)
    return value


def _swapped(text: str, swaps: tuple[tuple[str, str], ...]) -> str:
    for old, new in swaps:
        text = text.replace(old, new)
    return text


def _refresh_the_certified_digests(run_dir: Path) -> None:
    """Write in the manifest the size and the digest of each certified file as it now stands."""
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        target = run_dir / artifact["path"]
        if artifact["sha256"] is not None and target.is_file():
            artifact["sha256"], artifact["bytes"] = sha256_and_size(target)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def _check_no_name_left(project: Path, home: Path) -> None:
    """Refuse a run in which a file still holds the home folder or the user name."""
    pattern = re.compile(
        rf"{re.escape(str(home))}|/home/|C:\\Users|\b{re.escape(getpass.getuser())}\b"
    )
    host = re.compile(rf"\b{re.escape(socket.gethostname())}\b")
    left = []
    for path in sorted((project / "runs" / RUN).rglob("*")):
        if path.is_file() and path.suffix in {".json", ".log", ".md", ".toml"}:
            text = path.read_text(encoding="utf-8")
            if pattern.search(text) or host.search(text):
                left.append(path.relative_to(project).as_posix())
    if left:
        raise SystemExit("a file still names the machine: " + ", ".join(left))


# --------------------------------------------------------------------------- the expected values


def _expected(current: Path) -> dict[str, Any]:
    """Say the run in the numbers the test compares: its size, its digest and its values."""
    manifest = json.loads((current / "runs" / RUN / "manifest.json").read_text(encoding="utf-8"))
    return {
        "run": RUN,
        "sim_id": manifest["run"]["sim_id"],
        "cells": manifest["geometry"]["n_cells"],
        "periods": manifest["period"]["n_timesteps"],
        "hydromodpy_version": manifest["identity"]["hydromodpy_version"],
        "bytes": sum(item.stat().st_size for item in current.rglob("*") if item.is_file()),
        "tree_sha256": tree_digest(current),
        "values": manifest["values"]["digests"],
    }


def tree_digest(tree: Path) -> str:
    """Return the digest of the relative paths and the bytes of every file of a tree."""
    digest = hashlib.sha256()
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        digest.update(path.relative_to(tree).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


if __name__ == "__main__":
    main()
