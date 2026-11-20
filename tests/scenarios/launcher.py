"""Play one scenario through the real pipeline, in a folder and an environment of its own.

The scenario runs in a child process, as a user's command would. The child sees a
throwaway HOME, state and cache, one BLAS thread, and the solver binaries of the
machine linked into the cache. A scenario never fetches a binary.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs
import pytest

from hydromodpy.core.io.filesystem import link_or_copy
from tests.scenarios.factory import write_project

TIMEOUT_CODE = 124
MANIFEST = ".manifest.json"
_DROPPED_PREFIXES = ("HMP_", "XDG_")
_DROPPED_NAMES = ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "MPLCONFIGDIR")


@dataclass(frozen=True)
class Scenario:
    """One synthetic project and the command that plays it.

    A command scenario gives ``argv``, the arguments of ``python -m hydromodpy``.
    An API scenario gives ``python``, code run with ``python -c``.
    """

    name: str
    covers: str
    files: Mapping[str, str]
    argv: tuple[str, ...] = ()
    python: str = ""
    cwd: str = "."
    needs: tuple[str, ...] = ("mf6", "libmf6.so")
    expected_s: float = 10.0
    timeout_s: float = 600.0

    def __post_init__(self) -> None:
        if bool(self.argv) == bool(self.python):
            raise ValueError(f"scenario {self.name!r} needs exactly one of argv and python")


@dataclass(frozen=True)
class Played:
    """What a played scenario left behind."""

    name: str
    returncode: int
    seconds: float
    root: Path
    log: Path
    targets: tuple[tuple[str, str], ...]


def machine_bin_dir() -> Path:
    """Return the solver binary folder of the machine, read before any isolation."""
    override = os.environ.get("HMP_BIN")
    if override:
        return Path(override).expanduser().resolve()
    cache = os.environ.get("HMP_CACHE_HOME")
    base = (
        Path(cache).expanduser().resolve()
        if cache
        else Path(platformdirs.user_cache_dir("hydromodpy"))
    )
    return base / "bin"


def tree_root() -> Path:
    """Return the folder that holds the ``hydromodpy`` package this test run imports."""
    spec = importlib.util.find_spec("hydromodpy")
    if spec is None or spec.origin is None:
        raise RuntimeError("the hydromodpy package is not importable")
    return Path(spec.origin).resolve().parents[1]


def link_binaries(cache_home: Path, needs: Iterable[str]) -> Path:
    """Link the files of ``needs`` into ``cache_home/bin`` and return that folder.

    Each file is hard linked on its own, or copied where a link is refused, so
    the scenarios run on Windows without symbolic links. A missing file would
    otherwise be downloaded into the real cache, so the test is skipped instead.
    """
    source = machine_bin_dir()
    names = tuple(needs)
    for name in names:
        if not (source / name).is_file():
            pytest.skip(f"solver file is not installed: {source / name}")
    target = Path(cache_home) / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        link = target / name
        if not link.exists():
            link_or_copy(source / name, link)
    if (source / MANIFEST).is_file():
        shutil.copyfile(source / MANIFEST, target / MANIFEST)
    return target


def isolated_env(home: Path, cache_home: Path, state_home: Path, tmp: Path) -> dict[str, str]:
    """Return the environment of a scenario process, built from the one of the parent."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_DROPPED_PREFIXES) and key not in _DROPPED_NAMES
    }
    for folder in (home, cache_home, state_home, tmp):
        Path(folder).mkdir(parents=True, exist_ok=True)
    env.update(
        HOME=str(home),
        HMP_CACHE_HOME=str(cache_home),
        HMP_STATE_HOME=str(state_home),
        TMPDIR=str(tmp),
        PYTHONPATH=str(tree_root()),
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        RAYON_NUM_THREADS="1",
        PYTHONHASHSEED="42",
        MPLBACKEND="Agg",
        HMP_NO_PROGRESS="1",
        HMP_DETERMINISTIC_FETCHED_AT="1",
        TZ="UTC",
    )
    if os.name == "posix":
        env["LC_ALL"] = "C.UTF-8"
    return env


def find_targets(root: Path) -> tuple[tuple[str, str], ...]:
    """Return ``(kind, path)`` for each run and session folder under ``root``.

    A folder with ``manifest.json`` and ``fields.zarr`` is a run. A folder with
    ``session.json`` and ``trials.jsonl`` is a session. Paths are relative to
    ``root``, in POSIX form and in sorted order.
    """
    root = Path(root)
    found: list[tuple[str, str]] = []

    def walk(folder: Path) -> None:
        children = sorted(folder.iterdir())
        names = {child.name for child in children}
        relative = folder.relative_to(root).as_posix()
        if {"manifest.json", "fields.zarr"} <= names:
            found.append(("run", relative))
            return
        if {"session.json", "trials.jsonl"} <= names:
            found.append(("session", relative))
        for child in children:
            if child.is_dir() and not child.is_symlink() and child.name != ".hmp":
                walk(child)

    walk(root)
    return tuple(sorted(found, key=lambda target: target[1]))


def _command(scenario: Scenario) -> list[str]:
    if scenario.python:
        return [sys.executable, "-c", scenario.python]
    return [sys.executable, "-m", "hydromodpy", *scenario.argv]


def _kill(process: subprocess.Popen[bytes]) -> None:
    """Kill the child and the solver processes it started."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass  # the child ended between the timeout and the kill
    process.wait()


def play(scenario: Scenario, workdir: Path, env: Mapping[str, str], cache_home: Path) -> Played:
    """Write the project, run the scenario in a child process and report what it left.

    The log holds the output and the error stream of the child. A scenario that
    outlives ``timeout_s`` is killed and returns code 124. Nothing else is judged
    here, the calling test checks what its scenario covers.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    root = write_project(workdir / scenario.name, scenario.files)
    bin_dir = link_binaries(cache_home, scenario.needs)
    before = sorted(path.name for path in bin_dir.iterdir())
    log = workdir / f"{scenario.name}.log"
    start = time.monotonic()
    with open(log, "wb") as handle:
        process = subprocess.Popen(
            _command(scenario),
            cwd=root / scenario.cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        try:
            code = process.wait(timeout=scenario.timeout_s)
        except subprocess.TimeoutExpired:
            _kill(process)
            handle.write(f"\ntimeout after {scenario.timeout_s} s\n".encode())
            code = TIMEOUT_CODE
    seconds = round(time.monotonic() - start, 2)
    after = sorted(path.name for path in bin_dir.iterdir())
    if after != before:
        added = sorted(set(after) - set(before))
        raise AssertionError(f"the scenario tried to fetch a solver binary: {added}")
    targets = find_targets(root) if code == 0 else ()
    return Played(scenario.name, code, seconds, root, log, targets)


def play_script(
    name: str,
    files: Mapping[str, str],
    script: str,
    workdir: Path,
    env: Mapping[str, str],
    cache_home: Path,
    *,
    needs: tuple[str, ...] = (),
    timeout_s: float = 600.0,
) -> Played:
    """Write *files* under one folder and run the Python *script* there, in a child process.

    A script plays what one command cannot: several projects, several threads of
    one process, then a report of what it saw. It writes its findings to a file
    of the folder, and the calling test reads them.
    """
    scenario = Scenario(
        name=name,
        covers="a Python script over several projects",
        files=files,
        python=script,
        needs=needs,
        timeout_s=timeout_s,
    )
    return play(scenario, workdir, env, cache_home)
