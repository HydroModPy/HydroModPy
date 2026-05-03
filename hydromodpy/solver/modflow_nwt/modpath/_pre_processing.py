"""Pre-processing helpers for the MODPATH particle-tracking driver.

Builds the FloPy Modpath6 model from a MODFLOW-NWT run, then derives
starting locations from the injection raster.
"""

from __future__ import annotations

import os
from typing import Any

import flopy
import flopy.utils.binaryfile as fpu
import flopy.utils.postprocessing as pp
import numpy as np
import rasterio

from hydromodpy.core.logging import get_logger

from ._resolvers import ensure_modflow_name_file

logger = get_logger(__name__)


def load_modflow_for_modpath(
    *,
    full_path: str,
    model_name: str,
    model_modflow: Any,
    verbose: bool,
    check: bool,
) -> Any:
    """Load the MODFLOW-NWT model from the run folder for MODPATH consumption."""
    nam_file = ensure_modflow_name_file(
        full_path=full_path,
        model_name=model_name,
        model_modflow=model_modflow,
    )

    mf = flopy.modflow.Modflow.load(
        nam_file,
        model_ws=full_path,
        verbose=verbose,
        check=check,
        exe_name=getattr(model_modflow, "exe", None) or "mfnwt",
    )

    bas = mf.get_package("BAS6")
    if bas is None:
        bas_file = os.path.join(full_path, f"{model_name}.bas")
        bas = flopy.modflow.ModflowBas.load(bas_file, mf)
    upw = mf.get_package("UPW")
    if upw is None:
        lpf_file = os.path.join(full_path, f"{model_name}.upw")
        upw = flopy.modflow.ModflowUpw.load(lpf_file, mf, check=False)
    return mf


def build_modpath_model(
    *,
    mf: Any,
    full_path: str,
    model_name: str,
    exe: str,
    simfile_ext: str,
    namefile_ext: str,
    version: str,
) -> Any:
    """Instantiate the FloPy Modpath6 backend and attach the file paths."""
    head_file = os.path.join(full_path, f"{model_name}.hds")
    bud_file = os.path.join(full_path, f"{model_name}.cbc")
    dis_file = os.path.join(full_path, f"{model_name}.dis")

    mp = flopy.modpath.Modpath6(
        modelname=mf.name,
        model_ws=full_path,
        simfile_ext=simfile_ext,
        namefile_ext=namefile_ext,
        version=version,
        exe_name=exe,
        modflowmodel=mf,
        head_file=head_file,
        dis_unit=87,
        budget_file=bud_file,
    )
    mp.array_free_format = True
    mp.dis_file = dis_file
    mp.head_file = head_file
    mp.budget_file = bud_file
    return mp


def compute_seepage_zone(
    *,
    mf: Any,
    bud_file: str,
) -> np.ndarray:
    """Build the per-layer zone array for backward seepage tracking."""
    bas = mf.get_package("BAS6")
    upw = mf.get_package("UPW")
    nlay = mf.nlay
    nrow = mf.nrow
    ncol = mf.ncol
    ibound = bas.ibound.array

    cbb = fpu.CellBudgetFile(bud_file)
    rec_drn = cbb.get_data(kstpkper=(0, 0), text="DRAINS")
    rec_rch = cbb.get_data(kstpkper=(0, 0), text="RECHARGE")

    drn = np.ones((nrow, ncol))
    compti = 0
    comptj = 0
    for ii in range(0, rec_drn[0].shape[0]):
        drn[compti, comptj] = -1 * rec_drn[0][ii][1]
        comptj += 1
        if comptj == ncol:
            compti += 1
            comptj = 0
    rch = rec_rch[0][1]
    b = drn / rch
    b[np.isnan(b)] = 0
    szone = []
    for layer in range(0, nlay):
        a = np.zeros((nrow, ncol), dtype=int)
        if layer == 0:
            a[b >= 1] = 1
        a[ibound[layer] == -1] = 1
        szone.append(a)
    _ = upw  # keep package referenced for shape consistency
    return szone


def attach_starting_locations(
    *,
    mp: Any,
    mf: Any,
    zone_partic: str,
    track_dir: str,
    cell_div: int,
    bore_depth: list | None,
    sel_random: int | None,
    sel_slice: int | None,
    input_style: int,
) -> Any:
    """Build StartingLocationsFile entries and select the requested subset."""
    nlay = mf.nlay
    ncol = mf.ncol
    nrow = mf.nrow

    stl = flopy.modpath.mp6sim.StartingLocationsFile(model=mp, inputstyle=input_style)

    prow = cell_div
    pcol = cell_div
    play = nlay if bore_depth is not None else 1

    with rasterio.open(zone_partic) as src:
        mask_dem = src.read(1)

    head_file = mp.head_file
    hds_1c = fpu.HeadFile(head_file)
    head_1c = hds_1c.get_data(totim=hds_1c.get_times()[0])
    wt = pp.get_water_table(head_1c, -100)

    stldata = stl.get_empty_starting_locations_data(
        npt=int(np.sum(mask_dem > 0) * prow * pcol * play)
    )

    if track_dir == "forward":
        _populate_forward(
            stldata=stldata,
            mask_dem=mask_dem,
            wt=wt,
            mf=mf,
            nrow=nrow,
            ncol=ncol,
            nlay=nlay,
            prow=prow,
            pcol=pcol,
            play=play,
        )
    elif track_dir == "backward":
        _populate_backward(
            stldata=stldata,
            mask_dem=mask_dem,
            nrow=nrow,
            ncol=ncol,
            prow=prow,
            pcol=pcol,
            play=play,
            bore_depth=bore_depth,
        )

    point_data = _select_points(stldata, sel_random=sel_random, sel_slice=sel_slice)
    stl.data = point_data
    return point_data


def _populate_forward(
    *,
    stldata: np.ndarray,
    mask_dem: np.ndarray,
    wt: np.ndarray,
    mf: Any,
    nrow: int,
    ncol: int,
    nlay: int,
    prow: int,
    pcol: int,
    play: int,
) -> None:
    compt = 0
    for i in range(0, nrow):
        for j in range(0, ncol):
            if mask_dem[i, j] > 0:
                for r in range(prow):
                    for c in range(pcol):
                        for _l in range(play):
                            stldata[compt]["label"] = (
                                "p" + str(compt + 1) + "-" + str(r) + "-" + str(c)
                            )
                            for k in range(0, nlay):
                                if wt[i, j] > mf.dis.botm.array[k, i, j]:
                                    stldata[compt]["k0"] = k
                                    break
                            stldata[compt]["j0"] = j
                            stldata[compt]["i0"] = i
                            stldata[compt]["xloc0"] = (r + 0.5) / (prow)
                            stldata[compt]["yloc0"] = (c + 0.5) / (pcol)
                            if k == 0:
                                ztop = mf.dis.top.array[i, j]
                            else:
                                ztop = mf.dis.botm.array[k - 1, i, j]
                            zbot = mf.dis.botm.array[k, i, j]
                            thickness = ztop - zbot
                            if thickness <= 0:
                                aux_stl = 0.0
                            else:
                                aux_stl = min(max((wt[i, j] - zbot) / thickness, 0.0), 1.0)
                            stldata[compt]["zloc0"] = float(np.abs(aux_stl))
                            compt += 1


def _populate_backward(
    *,
    stldata: np.ndarray,
    mask_dem: np.ndarray,
    nrow: int,
    ncol: int,
    prow: int,
    pcol: int,
    play: int,
    bore_depth: list | None,
) -> None:
    compt = 0
    for i in range(0, nrow):
        for j in range(0, ncol):
            if mask_dem[i, j] > 0:
                for r in range(prow):
                    for c in range(pcol):
                        for layer_idx in range(play):
                            stldata[compt]["label"] = (
                                "p" + str(compt + 1) + "-" + str(r) + "-" + str(c)
                            )
                            stldata[compt]["j0"] = j
                            stldata[compt]["i0"] = i
                            stldata[compt]["xloc0"] = (r + 0.5) / (prow)
                            stldata[compt]["yloc0"] = (c + 0.5) / (pcol)
                            stldata[compt]["zloc0"] = 0.5
                            if bore_depth:
                                stldata[compt]["k0"] = layer_idx
                            else:
                                stldata[compt]["k0"] = 0
                            compt += 1


def _select_points(
    stldata: np.ndarray,
    *,
    sel_random: int | None,
    sel_slice: int | None,
) -> np.ndarray:
    """Subselect particles by random or slicing rule."""
    if sel_random is not None:
        if sel_random >= len(stldata):
            val_random = len(stldata) - 1
        else:
            val_random = sel_random
        point_data = np.random.choice(stldata, val_random)
        point_data = point_data.view(np.recarray)
        point_data = point_data[np.argsort(point_data["particleid"])]
    else:
        point_data = stldata

    if sel_slice is not None:
        point_data = stldata[::sel_slice]

    return point_data
