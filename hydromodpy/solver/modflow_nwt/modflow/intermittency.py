# -*- coding: utf-8 -*-
"""
* Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
*
* This program and the accompanying materials are made available under the
* terms of the Eclipse Public License 2.0 which is available at
* http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
* which is available at https://www.apache.org/licenses/LICENSE-2.0.
*
* SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

"""Intermittency index computation and export for MODFLOW-NWT post-processing.

The four intermittency variants (daily / weekly / monthly / yearly) share
identical logic and differ only in the time window size.  A single
``export_intermittency`` function replaces the four near-identical blocks
that previously appeared in ``Modflow.post_processing``.
"""

import os

import numpy as np
import rasterio

from hydromodpy.tools import get_logger

from .postprocess import NODATA

logger = get_logger(__name__)


def export_intermittency(
    label: str,
    window_size: int,
    acc_npy_raw: dict,
    result_dict: dict,
    tifs_file: str,
    watershed_dem: str,
    save_file: str,
    save_filename: str,
    toolbox,
) -> None:
    """
    Compute and export the intermittency index for a given time window.

    The intermittency index is the fraction of windows in which accumulated
    flow is positive (i.e. stream is active).  For each window, a binary
    raster is written to ``tifs_file``; the full time-series dict is saved
    as a ``.npy`` file in ``save_file``.

    Parameters
    ----------
    label : str
        Human-readable label used in log messages and output file names
        (e.g. ``"daily"``, ``"weekly"``, ``"monthly"``, ``"yearly"``).
    window_size : int
        Number of time steps per window (365 / 52 / 12 / 1).
    acc_npy_raw : dict
        Raw accumulation-flux dictionary loaded from ``accumulation_flux.npy``.
        Keys are integer time-step indices; values are 2-D flux arrays.
    result_dict : dict
        Dictionary to fill in-place with computed intermittency arrays.
        **Must be the dict matching** ``label`` (e.g. ``self.dict_intermittency_daily``).
    tifs_file : str
        Output folder for per-window raster files.
    watershed_dem : str
        Path to the reference DEM raster used for nodata masking and GeoTIFF
        metadata (via ``toolbox.export_tif``).
    save_file : str
        Output folder for the aggregated ``.npy`` dictionary.
    save_filename : str
        Base file name (without extension) for the ``.npy`` output
        (e.g. ``"intermittency_daily"``).
    toolbox : module
        HydroModPy toolbox module providing ``export_tif``.
    """
    if len(acc_npy_raw) < window_size:
        logger.warning(
            "Intermittency %s: not enough time steps (%d < %d), skipping.",
            label,
            len(acc_npy_raw),
            window_size,
        )
        np.save(os.path.join(save_file, save_filename), result_dict)
        return

    logger.info("Exporting %s intermittency maps", label)

    acc_npy = list(acc_npy_raw.items())
    n_steps = len(acc_npy_raw)
    n_windows = int(round(n_steps / window_size))

    inf = 0
    sup = window_size
    compt = 0

    for i in range(n_windows):
        logger.debug(
            "Processing %s intermittency t: %d / %d", label, i, n_windows
        )

        window = list(acc_npy)[inf:sup]

        with rasterio.open(watershed_dem) as src:
            mask = src.read(1)

        masked_window = [
            np.ma.masked_array(entry[1], mask=(mask < 0)) for entry in window
        ]

        # Count windows with positive flow
        zero = acc_npy_raw[0] * 0
        for arr in masked_window:
            tempo = arr.copy()
            tempo[tempo > 0] = 1
            zero = zero + tempo

        days_flux = np.ma.masked_array(zero, mask=(mask < 0))
        days_flux = np.ma.masked_array(days_flux, mask=(days_flux <= 0))

        for arr in masked_window:
            tempo = np.ma.masked_where(arr <= 0, arr)
            tempo[days_flux < window_size] = 0
            tempo[days_flux == window_size] = 1
            tempo_export = tempo.copy()
            result_dict[compt] = np.ma.masked_where(arr <= 0, tempo)
            tempo_export[arr <= 0] = NODATA
            tempo_export[mask <= 0] = NODATA
            output_path = os.path.join(
                tifs_file,
                f"intermittency_{label}_t({compt}).tif",
            )
            toolbox.export_tif(watershed_dem, tempo_export, output_path, NODATA)
            compt += 1

        inf += window_size
        sup += window_size

    np.save(os.path.join(save_file, save_filename), result_dict)
