"""The face flows of a MODFLOW-NWT run: pairs, sign, flat index and inactive cells."""

from __future__ import annotations

from pathlib import Path

import numpy as np

_SHAPE = (2, 2, 3)


def _faces() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Three records whose value at a cell is its flat index."""
    flat = np.arange(int(np.prod(_SHAPE)), dtype="float64").reshape(_SHAPE)
    return flat.copy(), flat.copy(), flat.copy()


def _active_with_cell_4_off() -> np.ndarray:
    active = np.ones(_SHAPE, dtype=bool)
    active[0, 1, 1] = False
    return active


# ``_extract_face_flows`` reads a CBC file. A fake one holds the records a
# MODFLOW-NWT run of the grid writes at one step, and nothing else.


class _FakeBudget:
    """One saved step of a CBC file: the records named, each a grid array."""

    def __init__(self, records: dict[str, np.ndarray]) -> None:
        self._arrays = list(records.values())
        self.recordarray = np.array(
            [(1, 1, 1, 86400.0, 86400.0, name.rjust(16).encode()) for name in records],
            dtype=[
                ("kstp", "i4"),
                ("kper", "i4"),
                ("imeth", "i4"),
                ("delt", "f8"),
                ("totim", "f8"),
                ("text", "S16"),
            ],
        )

    def get_record(self, index: int, full3D: bool = False) -> np.ndarray:
        return self._arrays[index]

    def close(self) -> None:
        pass


class _FakeStore:
    def __init__(self) -> None:
        self.stacks: dict[str, np.ndarray] = {}
        self.static: dict[str, np.ndarray] = {}

    def write_field_stack(self, sim_id, name, stack, *, n_timesteps) -> None:
        self.stacks[name] = stack

    def open_zarr(self, sim_id):
        store = self

        class _Zarr:
            def write_static_field(self, name, values) -> None:
                store.static[name] = values

            def close(self) -> None:
                pass

        return _Zarr()


def _extract(monkeypatch, records: dict[str, np.ndarray], shape) -> tuple[int, _FakeStore]:
    from hydromodpy.solver.modflow_nwt.extractors import flow

    monkeypatch.setattr(flow, "open_cell_budget", lambda path: _FakeBudget(records))
    monkeypatch.setattr(flow, "_active_cells", lambda *a: np.ones(shape, dtype=bool))
    store = _FakeStore()
    adapter = object.__new__(flow.ModflowNwtOutputAdapter)
    written = adapter._extract_face_flows(
        "sim",
        store,
        Path("model.cbc"),
        Path("."),
        "model",
        [(0, 0)],
        *shape,
        flux_scale_to_m3_s=0.5,
    )
    return written, store


def test_a_single_layer_run_writes_its_face_flows(monkeypatch) -> None:
    from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW

    shape = (1, 2, 2)
    right = np.zeros(shape)
    right[0, 0, 0] = 2.0
    front = np.zeros(shape)
    front[0, 0, 1] = -4.0
    written, store = _extract(
        monkeypatch, {"FLOW RIGHT FACE": right, "FLOW FRONT FACE": front}, shape
    )

    assert written == 4
    assert store.static[CONNECTION_CELLS].tolist() == [[0, 1], [0, 2], [1, 3], [2, 3]]
    # 2 m3/d leave cell 0 by its right face towards cell 1: the flow from the
    # first to the second cell is positive. 4 m3/d reach cell 1 from cell 3 by
    # the front face of cell 1: the flow from 1 to 3 is negative.
    np.testing.assert_array_equal(store.stacks[FACE_FLOW], [[1.0, 0.0, -2.0, 0.0]])


def test_a_face_record_missing_on_an_axis_longer_than_one_is_refused(monkeypatch) -> None:
    import pytest

    from hydromodpy.core.exceptions import ExtractError

    shape = (2, 2, 2)
    with pytest.raises(ExtractError, match="FLOW LOWER FACE"):
        _extract(
            monkeypatch,
            {"FLOW RIGHT FACE": np.zeros(shape), "FLOW FRONT FACE": np.zeros(shape)},
            shape,
        )
