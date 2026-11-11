"""The value digests of a run, taken at the seal or recomputed from the disk.

A seal compares values, not files. Three sources feed the one rule of
:mod:`hydromodpy.core.io.value_digest`:

- an array rounded at write time (the ``quantization`` attribute) has the
  digest of the float64 values the writer received, before the rounding. The
  writer records one digest per step in ``RunFacts.field_digests``, which
  survives a resume that does not read the extraction again; a step it never
  wrote is folded with the fill value read from the store.
- every other array of ``fields.zarr`` and every array of ``final_state/``
  has the digest of its stored values, read at the seal, which are the values
  the run computed when the store is exact.
- every floating column of every table of ``tables.parquet`` has the digest
  of its stored values; identity, clock and name columns are left out by
  ``IDENTITY_COLUMNS``, and the wall-clock rows by ``CLOCK_ROWS``, both
  written beside the schemas.

:func:`run_value_digests` takes all three at the seal. :func:`stored_value_digests`
reads the disk alone, for a 2.0.0 source and for a replay.
:func:`value_deltas` measures the keys that differ between two run directories.
"""

from __future__ import annotations

from collections.abc import Container, Mapping
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow.parquet as pq
import zarr

from hydromodpy.core.io.value_digest import (
    VALUES_RULE,
    ValueDigester,
    fold_steps,
    value_digest,
)
from hydromodpy.results.field_registry import AXIS_TIME
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    FINAL_STATE_DIRNAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)
from hydromodpy.schema.seal import ValueDigests

QUANTIZATION_ATTR: Final[str] = "quantization"
"""Attribute a rounded array carries; the writer records its float64 digests."""

FIELD_KEY_PREFIX: Final[str] = "fields/"
"""Prefix of the value key of an array of ``fields.zarr``."""


def run_value_digests(
    run_dir: str | Path,
    facts: Any,
    *,
    skip_columns: Container[str] | None = None,
) -> ValueDigests:
    """Return the digests of the values of a run, at the instant it seals.

    *facts* is the :class:`~hydromodpy.results.storage.run_facts.RunFacts` of the
    attempt, read for its ``field_digests``: one digest per step of each array
    rounded at write time, by array path.
    """
    root = Path(run_dir)
    registry = facts.field_digests
    digests: dict[str, str] = {}
    fields = root / FIELDS_STORE_NAME
    if fields.is_dir():
        for path, array in _arrays(fields):
            steps = registry.get(path)
            if steps is not None and QUANTIZATION_ATTR in array.attrs:
                digests[f"{FIELD_KEY_PREFIX}{path}"] = _fold_rounded(array, steps)
            else:
                digests[f"{FIELD_KEY_PREFIX}{path}"] = _array_digest(array)
    digests.update(_final_state_digests(root))
    digests.update(_table_digests(root, skip_columns))
    return ValueDigests(rule=VALUES_RULE, digests=dict(sorted(digests.items())))


def stored_value_digests(
    run_dir: str | Path, *, skip_columns: Container[str] | None = None
) -> ValueDigests:
    """Return the digests of the values a run directory holds today, read from the disk."""
    root = Path(run_dir)
    digests: dict[str, str] = {}
    fields = root / FIELDS_STORE_NAME
    if fields.is_dir():
        for path, array in _arrays(fields):
            digests[f"{FIELD_KEY_PREFIX}{path}"] = _array_digest(array)
    digests.update(_final_state_digests(root))
    digests.update(_table_digests(root, skip_columns))
    return ValueDigests(rule=VALUES_RULE, digests=dict(sorted(digests.items())))


def value_deltas(
    a_dir: str | Path, b_dir: str | Path, keys: Container[str]
) -> dict[str, dict[str, Any]]:
    """Measure each key that differs between two run directories.

    ``max_abs`` is the largest absolute difference on the cells both sides
    hold, and ``rel_l2`` the L2 norm of that difference over the L2 norm of
    the first directory's field. ``precision`` says whether the values were
    read exact or compact, because a rounded field cannot be measured finer
    than its rounding. A key one side does not store has two null measures.
    """
    first, second = Path(a_dir), Path(b_dir)
    deltas: dict[str, dict[str, Any]] = {}
    for key in sorted(keys):
        a = _values_of(first, key)
        b = _values_of(second, key)
        if a is None or b is None:
            deltas[key] = {"max_abs": None, "rel_l2": None, "precision": None, "reason": None}
            continue
        left, precision = a
        right, other_precision = b
        deltas[key] = {
            **_difference(left, right),
            "precision": "compact" if "compact" in (precision, other_precision) else "exact",
        }
    return deltas


def _difference(a: np.ndarray, b: np.ndarray) -> dict[str, float | str | None]:
    """Return ``max_abs`` and ``rel_l2``, null with a ``reason`` when no number measures it."""
    left = np.asarray(a, dtype=np.float64)
    right = np.asarray(b, dtype=np.float64)
    if left.shape != right.shape:
        return {"max_abs": None, "rel_l2": None, "reason": "shape"}
    finite_left = np.isfinite(left)
    finite_right = np.isfinite(right)
    if not np.array_equal(finite_left, finite_right):
        return {"max_abs": None, "rel_l2": None, "reason": "nan_pattern"}
    if not finite_left.any():
        return {"max_abs": 0.0, "rel_l2": 0.0, "reason": None}
    difference = left[finite_left] - right[finite_left]
    max_abs = float(np.abs(difference).max())
    norm = float(np.linalg.norm(left[finite_left]))
    difference_norm = float(np.linalg.norm(difference))
    if norm == 0.0 and difference_norm != 0.0:
        return {"max_abs": max_abs, "rel_l2": None, "reason": "zero_norm"}
    rel_l2 = 0.0 if norm == 0.0 else difference_norm / norm
    return {"max_abs": max_abs, "rel_l2": rel_l2, "reason": None}


def _array_digest(array: zarr.Array) -> str:
    """Return the digest of one array, folded per step when its first axis is time."""
    if _is_timed(array):
        digester = ValueDigester()
        for step in range(array.shape[0]):
            digester.update(step, np.asarray(array[step]))
        return digester.digest(array.shape[0])
    return value_digest(np.asarray(array[...]))


def _fold_rounded(array: zarr.Array, steps: Mapping[str, str]) -> str:
    """Fold the writer's per-step digests, filling a step it never wrote from the store."""
    recorded = {int(step): digest for step, digest in steps.items()}
    count = array.shape[0]
    for step in range(count):
        if step not in recorded:
            recorded[step] = value_digest(np.asarray(array[step]))
    return fold_steps(recorded, count)


def _is_timed(array: zarr.Array) -> bool:
    names = getattr(array.metadata, "dimension_names", None)
    return bool(names and names[0] == AXIS_TIME)


def _arrays(root: Path) -> list[tuple[str, zarr.Array]]:
    """Return every array of a Zarr group, by its path inside the group."""
    group = zarr.open_group(str(root), mode="r", use_consolidated=False)
    found: list[tuple[str, zarr.Array]] = []
    _walk(group, "", found)
    return sorted(found)


def _walk(group: zarr.Group, prefix: str, found: list[tuple[str, zarr.Array]]) -> None:
    for name, node in group.members():
        path = f"{prefix}{name}"
        if isinstance(node, zarr.Array):
            found.append((path, node))
        elif isinstance(node, zarr.Group):
            _walk(node, f"{path}/", found)


def _final_state_digests(root: Path) -> dict[str, str]:
    directory = root / FINAL_STATE_DIRNAME
    if not directory.is_dir():
        return {}
    return {
        f"final_state/{path}": value_digest(np.asarray(array[...]))
        for path, array in _arrays(directory)
    }


def _table_digests(root: Path, skip_columns: Container[str] | None) -> dict[str, str]:
    tables = root / TABLES_DIRNAME
    if not tables.is_dir():
        return {}
    skip = _identity_columns() if skip_columns is None else skip_columns
    digests: dict[str, str] = {}
    for path in sorted(tables.glob(f"*{PARQUET_FILE_SUFFIX}")):
        if not path.is_file():
            continue
        table = _without_clock_rows(pq.read_table(path), path.stem)
        for name, column in zip(table.column_names, table.columns, strict=True):
            if name in skip or not _is_quantity(column.type):
                continue
            digests[f"tables/{path.stem}/{name}"] = value_digest(
                np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)
            )
    return digests


def _without_clock_rows(table: Any, name: str) -> Any:
    """Drop the rows of *table* that carry a wall clock, by ``CLOCK_ROWS``."""
    import pyarrow.compute as pc

    from hydromodpy.results.storage.parquet_schemas import CLOCK_ROWS

    for table_name, column, value in CLOCK_ROWS:
        if table_name == name and column in table.column_names:
            table = table.filter(pc.fill_null(pc.not_equal(table[column], value), True))
    return table


def _is_quantity(kind: Any) -> bool:
    import pyarrow as pa

    return bool(pa.types.is_floating(kind))


def _identity_columns() -> frozenset[str]:
    """Return the columns no value digest reads, written beside the Parquet schemas."""
    from hydromodpy.results.storage.parquet_schemas import IDENTITY_COLUMNS

    return frozenset(IDENTITY_COLUMNS)


def _values_of(root: Path, key: str) -> tuple[np.ndarray, str] | None:
    if key.startswith(FIELD_KEY_PREFIX):
        return _array_values(root / FIELDS_STORE_NAME, key.removeprefix(FIELD_KEY_PREFIX))
    if key.startswith("final_state/"):
        return _array_values(root / FINAL_STATE_DIRNAME, key.removeprefix("final_state/"))
    if key.startswith("tables/"):
        _, table, column = key.split("/", 2)
        path = root / TABLES_DIRNAME / f"{table}{PARQUET_FILE_SUFFIX}"
        if not path.is_file():
            return None
        data = _without_clock_rows(pq.read_table(path), table).column(column)
        return np.asarray(data.to_numpy(zero_copy_only=False), dtype=np.float64), "exact"
    return None


def _array_values(root: Path, path: str) -> tuple[np.ndarray, str] | None:
    if not root.is_dir():
        return None
    group = zarr.open_group(str(root), mode="r", use_consolidated=False)
    if path not in group:
        return None
    array = group[path]
    precision = "compact" if QUANTIZATION_ATTR in array.attrs else "exact"
    return np.asarray(array[...]), precision


__all__ = [
    "FIELD_KEY_PREFIX",
    "QUANTIZATION_ATTR",
    "run_value_digests",
    "stored_value_digests",
    "value_deltas",
]
