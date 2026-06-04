"""Shared builders for the ``analysis.comparison.visuals`` helper tests.

Non-test module co-located with the split test files. It hosts the
``MapPayload`` factory helpers used by more than one test file.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.analysis.comparison.visuals_payloads import MapPayload


def _scatter_payload(
    *,
    simulation_id: str = "var",
    values: np.ndarray | None = None,
    cell_ids: np.ndarray | None = None,
    x: np.ndarray | None = None,
    y: np.ndarray | None = None,
    unit: str = "m",
    observable: str = "head",
    extent: tuple[float, float, float, float] | None = None,
) -> MapPayload:
    if values is None:
        values = np.array([1.0, 2.0, 3.0, 4.0])
    n = values.size
    if cell_ids is None:
        cell_ids = np.arange(n, dtype=int)
    if x is None:
        x = np.linspace(0.0, 3.0, n)
    if y is None:
        y = np.linspace(0.0, 3.0, n)
    return MapPayload(
        simulation_id=simulation_id,
        simulation_label=simulation_id.upper(),
        solver="modflow6",
        mesh_mode="structured",
        observable_name=observable,
        resolved_variable=observable,
        unit=unit,
        time_label="2024-01",
        values=np.asarray(values, dtype=float),
        geometry_kind="scatter",
        cell_ids=np.asarray(cell_ids, dtype=int),
        x=np.asarray(x, dtype=float),
        y=np.asarray(y, dtype=float),
        extent=extent,
    )


def _structured_payload(
    *,
    simulation_id: str = "var",
    shape: tuple[int, int] = (2, 2),
    values: np.ndarray | None = None,
    unit: str = "m",
    observable: str = "head",
    extent: tuple[float, float, float, float] | None = (0.0, 2.0, 0.0, 2.0),
) -> MapPayload:
    if values is None:
        values = np.arange(shape[0] * shape[1], dtype=float)
    return MapPayload(
        simulation_id=simulation_id,
        simulation_label=simulation_id.upper(),
        solver="modflow6",
        mesh_mode="structured",
        observable_name=observable,
        resolved_variable=observable,
        unit=unit,
        time_label="2024-01",
        values=np.asarray(values, dtype=float),
        geometry_kind="structured",
        structured_shape=shape,
        x=np.linspace(0.5, 1.5, shape[0] * shape[1]),
        y=np.linspace(0.5, 1.5, shape[0] * shape[1]),
        extent=extent,
    )
