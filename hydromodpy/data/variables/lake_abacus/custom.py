"""Custom lake-abacus data loader.

Normalises a user-provided abacus table (CSV/Parquet) into the internal
Parquet pivot and returns a :class:`TableRecord` pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.table import TableRecord
from hydromodpy.data.ingest import convert_abacus_to_parquet
from hydromodpy.data.provenance.derived import derived_path


def load_custom_abacus(
    source_cfg: Any,
    *,
    derived_dir: Path | None = None,
) -> list[TableRecord]:
    """Load a custom lake-abacus table as a :class:`TableRecord`.

    Both ``.csv`` and ``.parquet`` sources are normalised through the validated
    Parquet pivot when a ``derived_dir`` is available, so the abacus contract is
    enforced regardless of input format. A ``.parquet`` source without a
    ``derived_dir`` is referenced as-is (it cannot be re-written). The ``lake_id``
    from the source config (or the file stem) becomes the record's ``table_id``.
    The pivot is keyed on the source and the lake id, which it carries.
    ``derived_dir`` is never the user's data folder: a derived copy named like
    a user file would be taken for one.
    """
    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom lake-abacus path not found: {path}")

    lake_id = getattr(source_cfg, "lake_id", None) or path.stem
    ext = path.suffix.strip().lower()
    if ext not in (".csv", ".parquet"):
        raise ValueError(f"Unsupported lake-abacus format: '{ext}'. Supported: .csv, .parquet")

    if derived_dir is None:
        if ext == ".csv":
            raise ValueError(
                f"A derived_dir is required to convert a CSV lake-abacus to Parquet ({path.name})."
            )
        data: Path = path
    else:
        dest = derived_path(
            derived_dir, path, kind="pivot", suffix=".parquet", inputs=(str(lake_id),)
        )
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
