"""The flow between connected cells of a MODFLOW 6 run, read from its CBC file.

``FLOW-JA-FACE`` lists, for each cell, the flux through each of its connections
in the order of the grid ``ja``. MODFLOW counts positive what enters the cell
of the line, so the flow from a cell to its neighbour is the value at the
position that the neighbour's row gives back to the first. That value is kept
once per connection, positive from the smaller flat index to the larger, and
the diagonal is dropped: it is the residual of the cell, which the per-cell
budget already carries.

The store keeps one value per connection at each saved stamp, the mean of the
steps the stamp closes weighted by their length, in m3/s. ``connection_cells``
names the two cells of each connection, the smaller first.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.fields.precision import FieldPrecision, to_storage_precision
from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW
from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader
from hydromodpy.solver.modflow_common.period_steps import (
    StepKey,
    group_steps_by_stamp,
    weighted_period_mean,
)

__all__ = [
    "connection_pairs",
    "extract_face_flows",
    "grid_connections",
]


def grid_connections(solver_dir: Path) -> tuple[np.ndarray, np.ndarray, int] | None:
    """Return ``(ia, ja, ncpl)`` of the GWF grid, 0-based, from its ``.grb``."""
    grb_files = sorted(solver_dir.glob("*.disv.grb")) + sorted(solver_dir.glob("*.dis.grb"))
    if not grb_files:
        return None
    from flopy.mf6.utils import MfGrdFile

    grid = MfGrdFile(str(grb_files[0]), verbose=False)
    ia = np.asarray(grid.ia, dtype=np.int64)
    ja = np.asarray(grid.ja, dtype=np.int64)
    ncpl = int(grid.ncpl) if grid.grid_type == "DISV" else int(grid.nrow) * int(grid.ncol)
    return ia, ja, ncpl


def connection_pairs(ia: np.ndarray, ja: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the cell pairs of the grid and the ``FLOW-JA-FACE`` position of each.

    ``cells`` is ``(connection, 2)``, the smaller flat index first, sorted by
    the pair. ``positions`` holds, for each pair, the position of the second
    cell's connection back to the first: MODFLOW counts positive what enters
    the cell of the line, so ``flowja[positions[k]]`` is the flow from
    ``cells[k, 0]`` to ``cells[k, 1]``. A pair whose reverse connection the
    grid does not list touches an inactive cell and is left out.
    """
    ia = np.asarray(ia, dtype=np.int64)
    ja = np.asarray(ja, dtype=np.int64)
    rows = np.repeat(np.arange(ia.size - 1, dtype=np.int64), np.diff(ia))
    forward = ja > rows
    source = rows[forward]
    target = ja[forward]
    where = {
        (int(row), int(other)): pos for pos, (row, other) in enumerate(zip(rows, ja, strict=True))
    }
    pairs: list[tuple[int, int, int]] = []
    for first, second in zip(source, target, strict=True):
        position = where.get((int(second), int(first)))
        if position is not None:
            pairs.append((int(first), int(second), position))
    if not pairs:
        return np.zeros((0, 2), dtype=np.int32), np.zeros(0, dtype=np.int64)
    pairs.sort()
    cells = np.asarray([(first, second) for first, second, _ in pairs], dtype=np.int32)
    positions = np.asarray([position for _, _, position in pairs], dtype=np.int64)
    return cells, positions


def extract_face_flows(
    sim_id: str,
    store: Any,
    cbc_path: Path,
    solver_dir: Path,
    *,
    stamps: Sequence[StepKey],
    seconds_per_time_unit: float,
    precision: FieldPrecision,
) -> int:
    """Write ``face_flow`` and ``connection_cells`` of a MODFLOW 6 run.

    ``stamps`` are the 1-based ``(kstp, kper)`` of the saved heads. Each stamp
    gets the mean of the ``FLOW-JA-FACE`` records of the steps it closes,
    weighted by the ``delt`` of each record and divided by
    ``seconds_per_time_unit`` so the stored values are m3/s. A stamp no step
    reaches stays NaN. The array is written in ``precision``.

    Returns the number of connections written. Raises ``ExtractError`` when
    the binary grid or the record cannot give the connections of the run.
    """
    grid = grid_connections(solver_dir)
    if grid is None:
        raise ExtractError(
            f"No binary grid in {solver_dir}; the face flows of this run cannot be read"
        )
    ia, ja, _ = grid
    cells, positions = connection_pairs(ia, ja)
    if cells.shape[0] == 0:
        return 0
    budget = Mf6CellBudgetReader(cbc_path)
    try:
        # Each step keeps its index in the file, which ``read_record`` reads by.
        steps = [
            (index, record)
            for index, record in enumerate(budget.records)
            if record.text == "FLOW-JA-FACE"
        ]
        if not steps:
            raise ExtractError(
                f"{cbc_path.name} carries no FLOW-JA-FACE record; the face flows of "
                "this run cannot be read"
            )
        step_position: dict[StepKey, int] = {}
        step_lengths: list[float] = []
        for _, record in steps:
            key = (int(record.kstp), int(record.kper))
            if key not in step_position:
                step_position[key] = len(step_lengths)
                step_lengths.append(float(record.delt))
        groups = group_steps_by_stamp(list(step_position), step_lengths, stamps)
        placed: dict[int, tuple[int, float]] = {}
        for group in groups:
            for position, weight in zip(group.positions, group.weights, strict=True):
                placed[position] = (group.stamp, weight)
        values: dict[int, list[np.ndarray]] = {}
        weights: dict[int, list[float]] = {}
        for index, record in steps:
            key = (int(record.kstp), int(record.kper))
            stamp_weight = placed.get(step_position[key])
            if stamp_weight is None:
                continue
            flowja = np.asarray(budget.read_record(index), dtype="float64").reshape(-1)
            if flowja.size != ja.size:
                raise ExtractError(
                    f"FLOW-JA-FACE holds {flowja.size} values and the binary grid "
                    f"{ja.size}; the face flows of this run cannot be read"
                )
            stamp, weight = stamp_weight
            values.setdefault(stamp, []).append(flowja[positions])
            weights.setdefault(stamp, []).append(weight)
    finally:
        budget.close()
    stack = np.full((len(stamps), cells.shape[0]), np.nan, dtype="float64")
    for stamp, own in values.items():
        stack[stamp] = weighted_period_mean(own, weights[stamp]) / seconds_per_time_unit
    store.write_field_stack(
        sim_id, FACE_FLOW, to_storage_precision(stack, precision), n_timesteps=len(stamps)
    )
    zarr = store.open_zarr(sim_id)
    try:
        zarr.write_static_field(CONNECTION_CELLS, cells)
    finally:
        zarr.close()
    return int(cells.shape[0])
