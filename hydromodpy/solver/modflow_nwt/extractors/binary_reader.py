"""Thin, endianness-robust wrappers around MODFLOW binary output files.

FloPy's ``HeadFile``, ``CellBudgetFile`` and ``FormattedHeadFile`` readers
handle MODFLOW-NWT (.hds / .cbc) and MODFLOW 6 (.hds / .cbc / .fhd)
outputs but their constructor signatures differ slightly between the two
families. These helpers provide a single entry point that:

- accepts a precision hint (``single`` / ``double`` / ``auto``),
- normalises the endianness detection by trying both flavours when
  ``auto`` is requested,
- returns FloPy's reader instance unchanged so downstream code keeps
  calling ``get_data`` / ``get_ts``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

Precision = Literal["single", "double", "auto"]


def _open_with_precision(cls: type, path: Path, precision: str, **extra: Any):
    """Instantiate a FloPy reader with the requested precision."""
    return cls(str(path), precision=precision, **extra)


def open_head_file(
    path: str | Path,
    *,
    precision: Precision = "auto",
    text: str = "head",
) -> Any:
    """Return a FloPy ``HeadFile`` reader for a ``.hds`` / ``.fhd`` output.

    When *precision* is ``"auto"`` the function tries ``"double"`` first
    (MODFLOW 6 default), then falls back to ``"single"`` (MODFLOW-NWT
    default).
    """
    from flopy.utils.binaryfile import HeadFile

    path = Path(path)
    precisions: tuple[str, ...]
    precisions = (precision,) if precision != "auto" else ("double", "single")
    last_exc: Exception | None = None
    for prec in precisions:
        try:
            return _open_with_precision(HeadFile, path, prec, text=text)
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(
        f"Unable to open head file {path!s} with precisions {precisions}."
    ) from last_exc


def open_cell_budget_file(
    path: str | Path,
    *,
    precision: Precision = "auto",
) -> Any:
    """Return a FloPy ``CellBudgetFile`` reader for a ``.cbc`` output."""
    from flopy.utils.binaryfile import CellBudgetFile

    path = Path(path)
    precisions: tuple[str, ...]
    precisions = (precision,) if precision != "auto" else ("double", "single")
    last_exc: Exception | None = None
    for prec in precisions:
        try:
            return _open_with_precision(CellBudgetFile, path, prec)
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(
        f"Unable to open cell-budget file {path!s} with precisions {precisions}."
    ) from last_exc


def list_budget_records(cbc_reader: Any) -> list[str]:
    """Return the deduplicated record names present in a CBC file."""
    records = cbc_reader.get_unique_record_names(decode=True)
    return sorted({str(name).strip() for name in records})


__all__ = [
    "list_budget_records",
    "open_cell_budget_file",
    "open_head_file",
]
