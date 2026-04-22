"""Utilities used across hydromodpy.physics.hydrology.pyhelp.

This file was missing in the provided sources. It contains small, explicit
helpers that were previously assumed to exist.

Nothing in this module relies on environment variables or subprocesses.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Sequence
from pathlib import Path

import h5py
import numpy as np


def save_content_to_csv(filename: str | Path, content: list[list[str]]) -> None:
    """Save a list of rows (list of list of strings) to a text file.

    Historically PyHELP writes fixed-width formatted lines but stores them as
    a 'CSV' (one column). We preserve that behavior.
    """
    filename = str(filename)
    with open(filename, "w", encoding="utf-8", newline="") as fh:
        for row in content:
            if not row:
                fh.write("\n")
            else:
                # Each row is a single formatted string at index 0
                fh.write(str(row[0]))
                fh.write("\n")


def delete_folder_recursively(folder: str | Path) -> None:
    """Delete a folder and all its contents if it exists."""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)


def calc_dist_from_coord(
    lat0: float, lon0: float, lats: Sequence[float], lons: Sequence[float]
) -> np.ndarray:
    """Compute approximate distance (meters) between (lat0, lon0) and arrays.

    Uses a simple equirectangular approximation. For nearest-neighbor selection
    this is sufficient and fast.
    """
    lat0r = math.radians(lat0)
    lon0r = math.radians(lon0)
    latsr = np.radians(np.asarray(lats, dtype=float))
    lonsr = np.radians(np.asarray(lons, dtype=float))
    x = (lonsr - lon0r) * np.cos(0.5 * (latsr + lat0r))
    y = latsr - lat0r
    R = 6371000.0
    return R * np.sqrt(x * x + y * y)


def savedata_to_hdf5(hdf5: h5py.File, group_name: str, data: dict) -> None:
    """Save dict of arrays to an HDF5 group, creating it if needed."""
    if group_name in hdf5:
        grp = hdf5[group_name]
    else:
        grp = hdf5.create_group(group_name)

    for key, val in data.items():
        if key in grp:
            del grp[key]
        grp.create_dataset(key, data=val)
