"""Custom lake-abacus data loader.

Normalises a user-provided abacus table (CSV/Parquet) into the internal
Parquet pivot and returns a :class:`TableRecord` pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.adapters import convert_abacus_csv_to_parquet
from hydromodpy.data.contracts.table import TableRecord


def load_custom_abacus(
    source_cfg: Any,
    *,
    data_dir: Path | None = None,
) -> list[TableRecord]:
    """Load a custom lake-abacus table as a :class:`TableRecord`.

    A ``.csv`` source is converted to the validated Parquet pivot when a
    ``data_dir`` is available; otherwise the original path is referenced. The
    ``lake_id`` from the source config (or the file stem) becomes the
    record's ``table_id``.
    """
    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom lake-abacus path not found: {path}")

    lake_id = getattr(source_cfg, "lake_id", None) or path.stem
    ext = path.suffix.strip().lower()

    if ext == ".csv":
        if data_dir is None:
            raise ValueError(
                f"A data_dir is required to convert a CSV lake-abacus to Parquet ({path.name})."
            )
        dest = data_dir / f"lake_abacus_custom_{path.stem}.parquet"
        convert_abacus_csv_to_parquet(path, dest, lake_id=lake_id)
        data: Path = dest
    elif ext == ".parquet":
        data = path
    else:
        raise ValueError(f"Unsupported lake-abacus format: '{ext}'. Supported: .csv, .parquet")

    return [
        TableRecord(
            variable="lake_abacus",
            source="custom",
            table_id=str(lake_id),
            data=data,
            unit="m|m3|m2",
        )
    ]
