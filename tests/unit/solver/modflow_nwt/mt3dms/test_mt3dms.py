"""MT3DMS writes ``1e30`` in an inactive cell and the post-processing writes ``-9999`` where there is no seepage.

The UCN file holds ``cinact = 1e30`` in a cell with no concentration. The post-processing reads
it back as NaN, and writes the raster nodata ``-9999`` for a cell with no seepage, an inactive
cell, or a mass that is NaN. A concentration at seepage cells keeps its value, and a mass is the
concentration times the seepage.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.solver.modflow_nwt.mt3dms import mt3dms as mt3dms_module
from hydromodpy.solver.modflow_nwt.mt3dms.mt3dms import Mt3dms

_INACTIVE = 1.0e30
_NODATA = -9999.0


def _write_dem(path: Path) -> None:
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1.0, 1.0, 1.0),
        "nodata": _NODATA,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.array([[10.0]], dtype="float32"), 1)


def _post_process(monkeypatch, tmp_path: Path, concentration, seep, inactive) -> Mt3dms:
    class _Ucn:
        def __init__(self, _path: str) -> None:
            pass

        def get_alldata(self, mflay=None):
            del mflay
            return np.array([[[[0.0]]], [[[concentration]]]], dtype=float)

    monkeypatch.setattr(mt3dms_module.bf, "UcnFile", _Ucn)
    model = Mt3dms.__new__(Mt3dms)
    model.model_folder = str(tmp_path / "results")
    model.model_name = "demo"
    model.model_name_mt = "demo_mt"
    model.full_path = os.path.join(model.model_folder, "demo")
    Path(model.full_path).mkdir(parents=True)
    dem = tmp_path / "dem.tif"
    _write_dem(dem)
    geographic = SimpleNamespace(
        inactive_mask=np.array([[inactive]], dtype=bool),
        dem_watershed_path=str(dem),
        nper=1,
        routing_ctx=None,
        dict_outflow_drain={0: np.array([[seep]], dtype=float)},
    )
    model.post_processing(model_mt3dms=model, geographic=geographic)
    return model


# One row per cell: the concentration in the UCN file, the seepage, whether the cell is inactive,
# and the concentration and the mass written. The mass is concentration * seepage.
_CELLS = [
    pytest.param(2.0, 3.0, False, 2.0, 6.0, id="a_seeping_cell"),
    pytest.param(2.0, 0.0, False, _NODATA, _NODATA, id="no_seepage"),
    pytest.param(2.0, -1.0, False, _NODATA, _NODATA, id="a_negative_seepage_is_no_seepage"),
    pytest.param(2.0, 3.0, True, _NODATA, _NODATA, id="an_inactive_cell"),
    pytest.param(_INACTIVE, 3.0, False, np.nan, _NODATA, id="cinact_reads_back_as_nan"),
    pytest.param(3.0e30, 3.0, False, np.nan, _NODATA, id="anything_above_cinact_is_nan"),
    pytest.param(9.99e29, 1.0, False, 9.99e29, 9.99e29, id="below_cinact_is_a_concentration"),
]


@pytest.mark.parametrize(("concentration", "seep", "inactive", "conc", "mass"), _CELLS)
def test_the_seepage_rasters_carry_the_nodata_where_there_is_nothing_to_say(
    monkeypatch, tmp_path, concentration, seep, inactive, conc, mass
) -> None:
    model = _post_process(monkeypatch, tmp_path, concentration, seep, inactive)

    np.testing.assert_allclose(model.dict_concentration_seepage[0], [[conc]], rtol=1e-12)
    np.testing.assert_allclose(model.dict_mass_seepage[0], [[mass]], rtol=1e-12)


def test_the_inactive_concentration_written_is_the_one_read_back(monkeypatch) -> None:
    """``cinact`` of the BTN package is the threshold the post-processing reads."""
    recorded: dict[str, object] = {}

    class _Recorder:
        def __init__(self, *_args, **kwargs) -> None:
            recorded.update(kwargs)

    namespace = SimpleNamespace(
        mt3d=SimpleNamespace(
            Mt3dms=_Recorder,
            Mt3dGcg=_Recorder,
            Mt3dBtn=_Recorder,
            Mt3dAdv=_Recorder,
            mtdsp=SimpleNamespace(Mt3dDsp=_Recorder),
            mtrct=SimpleNamespace(Mt3dRct=_Recorder),
            Mt3dSsm=_Recorder,
        )
    )
    monkeypatch.setattr(mt3dms_module, "flopy", namespace)
    model = Mt3dms.__new__(Mt3dms)
    delr = SimpleNamespace(array=np.array([1.0]))
    model.mf = SimpleNamespace(nper=1, nlay=1, nrow=1, ncol=1)
    model.model_modflow = SimpleNamespace(
        dis=SimpleNamespace(delr=delr, delc=delr),
        nstp=[1],
        perlen=[1.0],
        sy=0.1,
    )
    model.model_name_mt = "demo_mt"
    model.full_path = "unused"
    model.exe = "mt3dusgs"
    model.new_stepsize = 1
    model.sconc_init = 0.0
    model.spc_name = "tracer"
    model.disp_long = model.disp_transh = model.disp_transv = 0.0
    model.diffu_coeff = 0.0
    model.react_order = None
    model.rate_decay = 0.0
    model.sconc_input = 0.0

    model.pre_processing()

    assert recorded["cinact"] == _INACTIVE
