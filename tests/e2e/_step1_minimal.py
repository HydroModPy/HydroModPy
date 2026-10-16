"""Run step 1 of example 04 in a disposable workspace, under a disposable HOME.

The workspace holds the regional DEM of the example (hard-linked when the
file system allows it) and a project made of ``project.toml`` and
``step1_minimal.toml``. The run goes through ``python -m hydromodpy``, as a
user's would. MODFLOW 6 comes from the binaries of the machine cache, linked
into the disposable cache; without them the test is skipped.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
DEM = REPO / "examples" / "data" / "dem" / "DEM_armorican_massif.tif"
MACHINE_BIN = Path.home() / ".cache" / "hydromodpy" / "bin"
RUN_NAME = "nancon_step1_minimal"


def disposable_env(home: Path) -> dict[str, str]:
    """Return the environment of a process that sees only a disposable HOME and cache."""
    if not (MACHINE_BIN / "mf6").is_file() or not (MACHINE_BIN / "libmf6.so").is_file():
        pytest.skip(f"MODFLOW 6 is not installed in {MACHINE_BIN}")
    cache = home / ".cache" / "hydromodpy"
    (cache / "bin").mkdir(parents=True, exist_ok=True)
    for name in ("mf6", "libmf6.so"):
        link = cache / "bin" / name
        if not link.exists():
            link.symlink_to(MACHINE_BIN / name)
    env = {key: value for key, value in os.environ.items() if key != "HMP_WORKSPACE"}
    env.update(
        HOME=str(home),
        HMP_CACHE_HOME=str(cache),
        HMP_STATE_HOME=str(home / ".local" / "state" / "hydromodpy"),
        MPLBACKEND="Agg",
    )
    return env


def make_workspace(root: Path) -> Path:
    """Return the project directory of a fresh workspace holding step 1 of example 04."""
    if not DEM.is_file():
        pytest.skip(f"the regional DEM of example 04 is not in this checkout: {DEM}")
    dem_dir = root / "data" / "dem"
    dem_dir.mkdir(parents=True)
    for source in (DEM, DEM.with_name(DEM.name + ".json")):
        if not source.is_file():
            continue
        try:
            os.link(source, dem_dir / source.name)
        except OSError:
            shutil.copy2(source, dem_dir / source.name)
    (root / "workspace.toml").write_text("[workspace]\n", encoding="utf-8")
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    shutil.copy2(EXAMPLE / "step1_minimal.toml", project / "step1_minimal.toml")
    shutil.copy2(EXAMPLE / "project.toml", project / "project.toml")
    return project


def hmp(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy <args>`` and return the finished process."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=900,
    )


def files_under(root: Path) -> set[Path]:
    """Return every file under *root*, relative to it."""
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
