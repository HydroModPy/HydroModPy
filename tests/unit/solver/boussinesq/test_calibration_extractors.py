"""Simulated discharge (m3/s) and heads (m) read from the state history of a Boussinesq trial.

The history is the ``_boussinesq_state_history.npz`` file of the scratch folder. Three cells
of 10 m2 stand for the mesh.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.calibration_extractors import (
    extract_discharge_history,
    extract_head_history_at_cells,
)

AREA_M2 = np.full(3, 10.0)


def write_history(folder: Path, **arrays: object) -> Path:
    np.savez(folder / "_boussinesq_state_history.npz", **arrays)
    return folder


def test_discharge_adds_positive_drain_and_excess(tmp_path: Path) -> None:
    folder = write_history(
        tmp_path,
        drainage_flux_history_m3_s=np.asarray([1.0, -2.0, 3.0]),
        saturation_excess_history_m_s=np.asarray([0.1, 0.2, -0.3]),
        cell_area_m2=AREA_M2,
    )

    series = extract_discharge_history(folder, catchment_mask=None)

    # Drain: 1 + 0 + 3 (the -2 is an inflow). Excess: 0.1 x 10 + 0.2 x 10 + 0.
    np.testing.assert_allclose(series.to_numpy(), [7.0])


def test_heads_of_the_last_snapshot_when_no_history(tmp_path: Path) -> None:
    folder = write_history(tmp_path, final_head_m=np.asarray([4.0, 5.0, 6.0]))

    series = extract_head_history_at_cells(folder, station_cells={"p": (0, 0, 2)})

    np.testing.assert_allclose(series["p"].to_numpy(), [6.0])


def test_initial_snapshot_closes_no_period(tmp_path: Path) -> None:
    folder = write_history(
        tmp_path,
        head_history_m=np.asarray([[1.0, 1.0, 1.0], [2.0, 3.0, 4.0]]),
        snapshot_elapsed_seconds=np.asarray([0.0, 3600.0]),
    )

    series = extract_head_history_at_cells(folder, station_cells={"p": (0, 0, 1)})

    np.testing.assert_allclose(series["p"].to_numpy(), [3.0])


REFUSALS = [
    pytest.param(
        extract_discharge_history,
        {},
        {"catchment_mask": None},
        FileNotFoundError,
        "No _boussinesq_state_history.npz",
        id="no history file",
    ),
    pytest.param(
        extract_discharge_history,
        {"drainage_flux_history_m3_s": np.asarray([])},
        {"catchment_mask": None},
        KeyError,
        "has no drainage_flux_history_m3_s",
        id="empty drain history",
    ),
    pytest.param(
        extract_discharge_history,
        {
            "drainage_flux_history_m3_s": np.zeros(3),
            "saturation_excess_history_m_s": np.zeros(3),
        },
        {"catchment_mask": None},
        KeyError,
        "no cell_area_m2",
        id="excess without areas",
    ),
    pytest.param(
        extract_head_history_at_cells,
        {"cell_area_m2": AREA_M2},
        {"station_cells": {"p": (0, 0, 0)}},
        KeyError,
        "has no head_history_m",
        id="no heads at all",
    ),
    pytest.param(
        extract_head_history_at_cells,
        {"final_head_m": np.zeros(3)},
        {"station_cells": {"p": (0, 0, 3)}},
        IndexError,
        "cell_id 3 is outside the Boussinesq mesh of 3 cells",
        id="station past the mesh",
    ),
    pytest.param(
        extract_head_history_at_cells,
        {"final_head_m": np.zeros(3)},
        {"station_cells": {"p": (1, 0, 0)}},
        ValueError,
        r"expects station cell \(0, 0, cell_id\)",
        id="station on a second layer",
    ),
]


@pytest.mark.parametrize(("read", "arrays", "kwargs", "error", "message"), REFUSALS)
def test_refusals(tmp_path: Path, read, arrays: dict, kwargs: dict, error, message: str) -> None:
    folder = write_history(tmp_path, **arrays) if arrays else tmp_path

    with pytest.raises(error, match=message):
        read(folder, **kwargs)
