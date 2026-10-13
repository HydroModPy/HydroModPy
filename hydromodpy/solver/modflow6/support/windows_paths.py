"""Refuse, on Windows, a MODFLOW 6 workspace whose paths mf6 cannot open.

mf6.exe and libmf6 open files through a Fortran runtime that is not long-path
aware. Past ``MAX_PATH`` the solve stops on a bare ``Could not open ...
IOSTAT error number 29`` or ``... does not exist``, which names neither the
length nor the remedy. Python writes the same files without complaint, so the
check runs after the files are written and before the solver starts.
"""

from __future__ import annotations

import os
from typing import Any

from hydromodpy.core.exceptions import SolverEnvironmentError

WINDOWS_SOLVER_PATH_LIMIT = 259
"""Longest path MODFLOW 6 opens on Windows: ``MAX_PATH`` is 260 with the NUL."""

_GRID_PACKAGE_TYPES = frozenset({"dis", "disv", "disu"})


def _output_names(package: Any) -> list[str]:
    """Return the files a package declares for MODFLOW 6 to write or read."""
    names: list[str] = []
    for block in package.blocks.values():
        for dataset_name, dataset in block.datasets.items():
            if dataset_name == "continuous":
                names.extend(str(name) for name in (dataset.get_data() or {}))
            elif dataset_name.endswith("filerecord"):
                rows = dataset.get_data()
                if rows is not None:
                    names.extend(str(row[0]) for row in rows)
    return names


def mf6_workspace_files(sim: Any) -> list[str]:
    """Return the absolute path of every file MODFLOW 6 opens for *sim*.

    The name files, every package file, the listings, the binary grid MF6
    writes beside each discretization, and the outputs the packages declare
    (heads, budgets, observation tables). An ``OPEN/CLOSE`` array outside the
    workspace is not listed.
    """
    sim_ws = str(sim.simulation_data.mfpath.get_sim_path())
    paths = [os.path.join(sim_ws, name) for name in ("mfsim.nam", "mfsim.lst")]
    for package in sim.sim_package_list:
        names = [package.filename, *_output_names(package)]
        paths.extend(os.path.join(sim_ws, name) for name in names)
    for model_name in sim.model_names:
        model = sim.get_model(model_name)
        model_ws = str(model.model_ws)
        namefile = str(model.name_file.filename)
        names = [namefile, f"{os.path.splitext(namefile)[0]}.lst"]
        for package in model.packagelist:
            names.append(package.filename)
            if package.package_type in _GRID_PACKAGE_TYPES:
                names.append(f"{package.filename}.grb")
            names.extend(_output_names(package))
        paths.extend(os.path.join(model_ws, name) for name in names)
    return [os.path.abspath(path) for path in paths]


def check_mf6_workspace_paths(sim: Any) -> None:
    """Raise when, on Windows, MODFLOW 6 cannot open a file of *sim*.

    Raises
    ------
    SolverEnvironmentError
        The longest path is over :data:`WINDOWS_SOLVER_PATH_LIMIT`. The message
        names the path, its length and the remedy.
    """
    if os.name != "nt":
        return
    longest = max(mf6_workspace_files(sim), key=len)
    if len(longest) <= WINDOWS_SOLVER_PATH_LIMIT:
        return
    raise SolverEnvironmentError(
        f"[HMPY.E406] MODFLOW 6 cannot open {longest}: the path is {len(longest)} "
        f"characters, and on Windows mf6 opens no path longer than "
        f"{WINDOWS_SOLVER_PATH_LIMIT}. Move the project to a shorter folder "
        f"(for example C:\\hmp\\<project>) or give the simulation a shorter name.",
        path=longest,
        length=len(longest),
    )
