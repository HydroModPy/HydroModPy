"""The GWT extractor reads the MODFLOW 6 concentration layout.

MODFLOW 6 GWT writes its concentration file in the head layout, double
precision. Read as an MT3DMS UcnFile, the header gave a grid of
538 976 334 columns and flopy warned "Very large grid".
"""

from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.results.zarr_store.zarr_reader import concentration_array
from hydromodpy.solver.modflow6.extractors.transport import Modflow6GwtOutputAdapter
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run


def _write_mf6_concentration(path: Path, frames: list[np.ndarray]) -> None:
    """Write one-layer frames as MODFLOW 6 does: stream access, double precision."""
    nrow, ncol = frames[0].shape
    with path.open("wb") as handle:
        for index, frame in enumerate(frames):
            np.array([index + 1, 1], dtype="<i4").tofile(handle)
            np.array([float(index + 1), float(index + 1)], dtype="<f8").tofile(handle)
            handle.write(b"CONCENTRATION".rjust(16))
            np.array([ncol, nrow, 1], dtype="<i4").tofile(handle)
            np.asarray(frame, dtype="<f8").tofile(handle)


class _Store:
    sim_id = "sim"

    def __init__(self) -> None:
        self.stacks: list[np.ndarray] = []

    def write_field_stack(
        self, sim_id, name, chunk, *, n_timesteps, timestep_offset, subgroup=None
    ) -> None:
        assert name == "NO3"
        assert subgroup == "concentration"
        self.stacks.append(np.array(chunk))


def test_the_gwt_extractor_reads_every_frame_without_a_grid_warning(tmp_path: Path) -> None:
    frames = [np.full((1, 3), 0.25), np.full((1, 3), 0.5)]
    _write_mf6_concentration(tmp_path / "gwt.ucn", frames)
    store = _Store()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Modflow6GwtOutputAdapter().extract(
            solved_run(tmp_path, options=SimpleNamespace(spc_name="NO3")), store, keep_all
        )

    assert not [w for w in caught if "Very large grid" in str(w.message)]
    stack = np.concatenate(store.stacks)
    assert stack.shape == (2, 1, 3)
    np.testing.assert_allclose(stack[:, 0, 0], [0.25, 0.5])


def test_the_gwt_extractor_writes_into_a_simulation_zarr_read_back_by_concentration_array(
    tmp_path: Path,
) -> None:
    frames = [np.full((1, 3), 0.25), np.full((1, 3), 0.5)]
    _write_mf6_concentration(tmp_path / "gwt.ucn", frames)
    zarr_store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=3, n_layers=1)
    store = SimpleNamespace(
        sim_id="sim",
        write_field_stack=lambda sim_id, var, chunk, **kw: zarr_store.write_field_stack(
            var, chunk, **kw
        ),
    )

    Modflow6GwtOutputAdapter().extract(
        solved_run(tmp_path, options=SimpleNamespace(spc_name="NO3")), store, keep_all
    )

    arr = concentration_array(zarr_store.root)
    assert arr.shape == (2, 1, 3)
    np.testing.assert_allclose(np.asarray(arr)[:, 0, 0], [0.25, 0.5])
    zarr_store.close()
