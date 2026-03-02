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

"""Cross-section plots for MODFLOW-NWT pre-processing diagnostics."""

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import flopy

from .nwt_options import ModflowPreprocessOptions

_NODATA = -9999


def plot_cross_section(
    mf,
    hk: np.ndarray,
    sy: np.ndarray,
    dem: np.ndarray,
    model_name: str,
    options: ModflowPreprocessOptions,
) -> None:
    """
    Plot West-East (K) and North-South (Sy) cross-sections of the MODFLOW grid.

    One panel shows hydraulic conductivity ``K`` [m/s] along the central row
    (West-East direction); the other shows specific yield ``Sy`` [%] along the
    central column (North-South direction).  Both use a log-normalised colour
    scale.

    Parameters
    ----------
    mf : flopy.modflow.Modflow
        Initialised FloPy MODFLOW model object.
    hk : np.ndarray
        Hydraulic conductivity array (MODFLOW convention, [m/day]).
    sy : np.ndarray
        Specific yield array (dimensionless).
    dem : np.ndarray
        DEM array used to set cross-section y-axis limits when
        ``options.cross_ylim`` is ``None``.
    model_name : str
        Model name displayed as figure title.
    options : ModflowPreprocessOptions
        Pre-processing options; ``plot_cross`` must be ``True`` for this
        function to be called.  ``cross_ylim`` overrides automatic y-limits.
    """
    fig, axs = plt.subplots(1, 2, figsize=(14, 4), dpi=300)
    axs = axs.ravel()

    grid_model = mf.modelgrid

    # West-East cross-section: hydraulic conductivity [m/s]
    modelxsect1 = flopy.plot.PlotCrossSection(
        model=mf, line={"Row": int(grid_model.shape[1] / 2)}
    )
    imhk = modelxsect1.plot_array(
        hk / 24 / 3600,
        masked_values=[_NODATA],
        cmap="jet",
        alpha=0.5,
        lw=0.1,
        ax=axs[0],
        norm=mpl.colors.LogNorm(vmin=1e-10, vmax=1e-1),
    )
    axs[0].set_title("West-East (Row), K [m/s]", fontsize=12)
    if options.cross_ylim is None:
        dem_valid = np.ma.masked_equal(dem, _NODATA, copy=False)
        axs[0].set_ylim(np.nanmin(dem_valid), np.nanmax(dem_valid))
    else:
        axs[0].set_ylim(options.cross_ylim[0], options.cross_ylim[1])
    axs[0].set_xlabel("Distance [m]")
    axs[0].set_ylabel("Elevation [m]")
    fig.colorbar(imhk)

    # North-South cross-section: specific yield [%]
    modelxsect2 = flopy.plot.PlotCrossSection(
        model=mf, line={"Column": int(grid_model.shape[2] / 2)}
    )
    imsy = modelxsect2.plot_array(
        sy * 100,
        masked_values=[_NODATA],
        cmap="jet",
        alpha=0.5,
        lw=0.1,
        ax=axs[1],
        norm=mpl.colors.LogNorm(vmin=0.1, vmax=100),
    )
    axs[1].set_title("North-South (Column), Sy [%]", fontsize=12)
    if options.cross_ylim is None:
        dem_valid = np.ma.masked_equal(dem, _NODATA, copy=False)
        axs[1].set_ylim(np.nanmin(dem_valid), np.nanmax(dem_valid))
    else:
        axs[1].set_ylim(options.cross_ylim[0], options.cross_ylim[1])
    axs[1].set_xlabel("Distance [m]")
    axs[1].set_ylabel("Elevation [m]")
    fig.colorbar(imsy)

    fig.suptitle(model_name.upper(), y=1.0, fontsize=10)
    fig.tight_layout()
