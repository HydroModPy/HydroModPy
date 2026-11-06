"""The GWT extractor reads the MODFLOW 6 concentration layout.

MODFLOW 6 GWT writes its concentration file in the head layout, double
precision. Read as an MT3DMS UcnFile, the header gave a grid of
538 976 334 columns and flopy warned "Very large grid".
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow6.extractors.transport import Modflow6GwtOutputAdapter


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
    def __init__(self) -> None:
        self.stacks: list[np.ndarray] = []

    def write_field_stack(self, sim_id, name, chunk, *, n_timesteps, timestep_offset) -> None:
        assert name == "concentration"
        self.stacks.append(np.array(chunk))


def test_the_gwt_extractor_reads_every_frame_without_a_grid_warning(tmp_path) -> None:
    frames = [np.full((1, 3), 0.25), np.full((1, 3), 0.5)]
    _write_mf6_concentration(tmp_path / "gwt.ucn", frames)
    store = _Store()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Modflow6GwtOutputAdapter().extract("sim", tmp_path, store, model_name="gwt")

    assert not [w for w in caught if "Very large grid" in str(w.message)]
    stack = np.concatenate(store.stacks)
    assert stack.shape == (2, 1, 3)
    np.testing.assert_allclose(stack[:, 0, 0], [0.25, 0.5])
