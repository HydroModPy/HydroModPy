"""Custom lake-abacus data loader.

Normalises a user-provided abacus table (CSV/Parquet) into the internal
Parquet pivot and returns a :class:`TableRecord` pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.adapters import convert_abacus_to_parquet
from hydromodpy.data.contracts.table import TableRecord


def load_custom_abacus(
    source_cfg: Any,
    *,
    data_dir: Path | None = None,
) -> list[TableRecord]:
    """Load a custom lake-abacus table as a :class:`TableRecord`.

    Both ``.csv`` and ``.parquet`` sources are normalised through the validated
    Parquet pivot when a ``data_dir`` is available, so the abacus contract is
    enforced regardless of input format. A ``.parquet`` source without a
    ``data_dir`` is referenced as-is (it cannot be re-written). The ``lake_id``
    from the source config (or the file stem) becomes the record's ``table_id``.
    """
    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom lake-abacus path not found: {path}")

    lake_id = getattr(source_cfg, "lake_id", None) or path.stem
    ext = path.suffix.strip().lower()
    if ext not in (".csv", ".parquet"):
        raise ValueError(f"Unsupported lake-abacus format: '{ext}'. Supported: .csv, .parquet")

    if data_dir is None:
        if ext == ".csv":
            raise ValueError(
                f"A data_dir is required to convert a CSV lake-abacus to Parquet ({path.name})."
            )
        data: Path = path
    else:
        dest = data_dir / f"lake_abacus_custom_{path.stem}.parquet"
        convert_abacus_to_parquet(path, dest, lake_id=lake_id)
        data = dest

    return [
        TableRecord(
            variable="lake_abacus",
            source="custom",
            table_id=str(lake_id),
            data=data,
            unit="m|m3|m2",
        )
    ]
