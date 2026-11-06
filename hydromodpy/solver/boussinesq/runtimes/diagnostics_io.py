"""Small readers and writers the Boussinesq diagnostic files share.

Each diagnostic writer turns runtime records into CSV rows and JSON values the
same way: missing values become empty cells, numpy values become plain Python,
non-finite floats become null, and a value that does not parse takes its
default.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool | int | float | str):
        return value
    return json.dumps(jsonable(value), ensure_ascii=True)


def jsonable_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): jsonable(value) for key, value in values.items()}


def jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def float_list(value: Any) -> list[float]:
    if not isinstance(value, list | tuple):
        return []
    return [float_value(item, math.nan) for item in value]


def bool_list(value: Any) -> list[bool]:
    if not isinstance(value, list | tuple):
        return []
    return [bool(item) for item in value]


def int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def float_value(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def sum_int(rows: list[Mapping[str, Any]], key: str) -> int:
    return int(sum(int_value(row.get(key), 0) for row in rows))


def max_int(rows: list[Mapping[str, Any]], key: str) -> int:
    values = [int_value(row.get(key), 0) for row in rows]
    return int(max(values)) if values else 0


def max_float(rows: list[Mapping[str, Any]], key: str) -> float:
    values = [float_value(row.get(key), 0.0) for row in rows]
    return float(max(values)) if values else 0.0


def list_get(values: list[Any], index: int, default: Any = None) -> Any:
    if 0 <= int(index) < len(values):
        return values[int(index)]
    return default


def finite_values(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    return array[np.isfinite(array)]


def finite_min(values: np.ndarray) -> float | None:
    finite = finite_values(values)
    return None if finite.size == 0 else float(np.min(finite))


def finite_max(values: np.ndarray) -> float | None:
    finite = finite_values(values)
    return None if finite.size == 0 else float(np.max(finite))


def finite_sum(values: np.ndarray) -> float | None:
    finite = finite_values(values)
    return None if finite.size == 0 else float(np.sum(finite))


__all__ = [
    "bool_list",
    "csv_value",
    "finite_max",
    "finite_min",
    "finite_sum",
    "finite_values",
    "float_list",
    "float_value",
    "int_value",
    "jsonable",
    "jsonable_mapping",
    "list_get",
    "max_float",
    "max_int",
    "sum_int",
    "write_csv",
]
