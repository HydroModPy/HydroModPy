"""Lake abacus reader extracting stage-volume-area curves from loaded tables."""

from __future__ import annotations

from typing import Any


def _abacus_columns(frame: Any) -> dict[str, list[float]]:
    """Return the ``{stage, volume, sarea}`` column mapping from an abacus frame."""
    return {
        column: [float(value) for value in frame[column].tolist()]
        for column in ("stage", "volume", "sarea")
    }


def lake_abacus(
    result: Any,
    lake_ids: list[str],
) -> dict[str, dict[str, list[float]]]:
    """Match each abacus record's stage-volume-area rows to a lake id.

    The input `result` may be a LoadResult with a `.tables` sequence of
    TableRecord objects, or an iterable of records directly.
    """
    import pandas as pd

    if result is None:
        return {}
    records = list(getattr(result, "tables", result) or [])
    if not records:
        return {}

    abacus_by_lake: dict[str, dict[str, list[float]]] = {}
    for record in records:
        data_path = getattr(record, "data", record)
        if not data_path:
            continue
        frame = pd.read_parquet(str(data_path))
        if "lake_id" in frame.columns:
            for lake_id, group in frame.groupby("lake_id"):
                abacus_by_lake[str(lake_id)] = _abacus_columns(group)
        else:
            table_id = str(getattr(record, "table_id", "") or "")
            target = table_id if table_id in lake_ids else (lake_ids[0] if lake_ids else None)
            if target is not None:
                abacus_by_lake[target] = _abacus_columns(frame)
    return abacus_by_lake
