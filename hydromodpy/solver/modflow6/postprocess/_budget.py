"""Budget-record helpers for MODFLOW-6 cell-by-cell flow files."""

from __future__ import annotations

import flopy.utils.binaryfile as bf
import numpy as np

from ._models import BudgetReaderLike, FlowPostprocessModel


def get_budget_records_or_none(
    cbb: BudgetReaderLike,
    *,
    kstpkper: tuple[int, int],
    text: str,
):
    """Return one budget term, or None when the term is absent from the file."""
    try:
        return cbb.get_data(kstpkper=kstpkper, text=text)
    except Exception as exc:
        message = str(exc)
        if "text string is not in the budget file" in message.lower():
            return None
        raise


def open_budget_file(path: str):
    """Open one MF6 cell-budget file with a small precision fallback chain."""
    for kwargs in ({}, {"precision": "double"}, {"precision": "single"}):
        try:
            return bf.CellBudgetFile(path, **kwargs)
        except TypeError:
            if kwargs:
                continue
            raise
        except Exception:
            if kwargs == {"precision": "single"}:
                raise
            continue


def compute_drain_outflow_and_seepage(
    drain_records,
    *,
    ncpl: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map MF6 DRN records to per-cell outflow and seepage flags."""
    outflow = np.zeros(int(ncpl), dtype=float)
    seepage = np.zeros(int(ncpl), dtype=float)
    if drain_records is None or len(drain_records) == 0:
        return outflow, seepage

    record = drain_records[0]
    try:
        if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
            node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
            q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
            iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
        else:
            iterator = ((int(item[0]), float(item[-1])) for item in record)
        for node, q in iterator:
            if node <= 0:
                continue
            layer = (node - 1) // int(ncpl)
            cell_id = (node - 1) % int(ncpl)
            if layer == 0:
                outflow[cell_id] += max(-q, 0.0)
                seepage[cell_id] = 1.0 if q < 0 else seepage[cell_id]
    except Exception:
        return np.zeros(int(ncpl), dtype=float), np.zeros(int(ncpl), dtype=float)
    return outflow, seepage


def east_side_cell_ids(model: FlowPostprocessModel) -> set[int]:
    """Return east-boundary cell ids for one DISV topological layer."""
    if getattr(model.solver_mesh, "is_structured", False):
        nrow = int(model.nrow)
        ncol = int(model.ncol)
        return {row * ncol + (ncol - 1) for row in range(nrow)}
    support = getattr(model, "runtime_mesh_support", None)
    if support is None:
        return set()
    return {
        int(cell_id) for cell_id in support.boundary_cell_indices_for_side("east_side").tolist()
    }


def compute_chd_outlet_discharge_east_side_m3_s(
    chd_records,
    *,
    ncpl: int,
    east_side_cell_ids: set[int],
) -> float:
    """Return total positive east-side CHD outflow [m3/s] for one stress period."""
    if not chd_records or not east_side_cell_ids:
        return 0.0

    record = chd_records[0]
    if record is None or len(record) == 0:
        return 0.0

    if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
        node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
        q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
        iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
    else:
        iterator = ((int(item[0]), float(item[-1])) for item in record)

    discharge_m3_s = 0.0
    for node, q in iterator:
        if node <= 0:
            continue
        cell_id = (int(node) - 1) % int(ncpl)
        if cell_id not in east_side_cell_ids:
            continue
        discharge_m3_s += max(-float(q), 0.0)
    return float(discharge_m3_s)
