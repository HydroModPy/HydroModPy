"""A run holds on a shared, read-only install of the solver, and stays within its path budget.

One project folder, the island of ``factory.py`` played by MODFLOW 6 through
``libmf6``. Three steps:

1. A folder ``shared_bin/`` receives ``mf6`` and ``libmf6`` by ``link_or_copy``,
   then becomes read-only (outside Windows). The environment names it in
   ``HMP_BIN`` and holds an empty ``HMP_CACHE_HOME``. ``hmp run island.toml``
   ends in 0, ``shared_bin/`` keeps the same files, sizes and dates, no
   ``bin/`` folder appears in the cache, and the provenance of the run names
   the host by ``host_name()``.
2. ``hmp publish island --to copy``, then ``hmp workspace init`` and
   ``hmp project new other``, and in that project ``hmp catalog import copy
   --name island_copy``: the import moves the copy onto the folder it
   reserved, and ``hmp catalog show island_copy`` reads the imported run.
3. The longest path written below each project folder, measured by a walk,
   holds ``PROJECT_TREE_DEPTH`` characters at most. A deeper file means the
   budget of ``core/io/filesystem.py`` must be measured again.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from hydromodpy.core.io.filesystem import PROJECT_TREE_DEPTH, link_or_copy
from hydromodpy.core.state.host import host_name
from hydromodpy.results.storage.contract import RUN_PROVENANCE_FILENAME
from hydromodpy.solver.modflow_common.binaries import exe_filename
from tests.scenarios.factory import LIBMF6_TAIL, transient_island, write_project
from tests.scenarios.launcher import MANIFEST, isolated_env, machine_bin_dir

SOLVERS = ("mf6", "libmf6")


def _hmp(root: Path, env: dict[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* with the environment of the scenario."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """The tail of the command output, the part a failure prints."""
    return result.stderr[-3000:]


def _shared_bin(folder: Path) -> Path:
    """Fill *folder* with the solver files of the machine, linked or copied."""
    source = machine_bin_dir()
    names = tuple(exe_filename(solver) for solver in SOLVERS)
    for name in names:
        if not (source / name).is_file():
            pytest.skip(f"solver file is not installed: {source / name}")
    folder.mkdir()
    for name in names:
        link_or_copy(source / name, folder / name)
    if (source / MANIFEST).is_file():
        shutil.copyfile(source / MANIFEST, folder / MANIFEST)
    return folder


def _listing(folder: Path) -> dict[str, tuple[int, int]]:
    """Name, size and modification time of each file of *folder*."""
    return {
        entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns)
        for entry in sorted(folder.iterdir())
    }


def _longest_below(root: Path) -> tuple[int, str]:
    """Length of the longest path below *root*, counted from the end of *root*, and that path."""
    base = len(str(root))
    longest = (0, "")
    for folder, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            path = os.path.join(folder, name)
            longest = max(longest, (len(path) - base, path))
    return longest


def test_a_run_holds_on_a_shared_install(tmp_path: Path) -> None:
    shared = _shared_bin(tmp_path / "shared_bin")
    cache_home = tmp_path / "cache"
    env = isolated_env(tmp_path / "home", cache_home, tmp_path / "state", tmp_path / "tmp")
    env["HMP_BIN"] = str(shared)
    root = write_project(
        tmp_path / "project",
        {"island.toml": transient_island("island", "modflow6", tail=LIBMF6_TAIL)},
    )
    before = _listing(shared)
    if os.name != "nt":
        shared.chmod(0o555)
    try:
        # 1. The run reads the shared install and writes nothing there nor in the cache.
        ran = _hmp(root, env, "run", "island.toml")
        assert ran.returncode == 0, _said(ran)
    finally:
        shared.chmod(stat.S_IRWXU)
    assert _listing(shared) == before
    assert not (cache_home / "bin").exists()
    source = root / "runs" / "island"
    provenance = json.loads((source / RUN_PROVENANCE_FILENAME).read_text(encoding="utf-8"))
    assert provenance["platform"]["hostname"] == host_name()

    # 2. A published copy is imported into another project, onto the folder it reserved.
    copy = tmp_path / "copy"
    published = _hmp(root, env, "publish", "island", "--to", str(copy))
    assert published.returncode == 0, _said(published)
    workspace = tmp_path / "workspace"
    initialised = _hmp(tmp_path, env, "workspace", "init", str(workspace))
    assert initialised.returncode == 0, _said(initialised)
    created = _hmp(tmp_path, env, "project", "new", "other", "-w", str(workspace))
    assert created.returncode == 0, _said(created)
    other = workspace / "projects" / "other"
    imported = _hmp(other, env, "catalog", "import", str(copy), "--name", "island_copy")
    assert imported.returncode == 0, _said(imported)
    assert (other / "runs" / "island_copy" / "manifest.json").is_file()
    shown = _hmp(other, env, "catalog", "show", "island_copy")
    assert shown.returncode == 0, _said(shown)

    # 3. Nothing below a project folder is deeper than the budget of a Windows project.
    for project in (root, other):
        depth, deepest = _longest_below(project)
        assert depth <= PROJECT_TREE_DEPTH, (depth, deepest)
