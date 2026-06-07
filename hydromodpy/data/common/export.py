"""CSV export: chronicles, metadata, and table of contents."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.io_helpers import safe_file_token
from hydromodpy.data.contracts.timeseries import PointRecord

logger = get_logger(__name__)


def export_records(
    records: list[PointRecord],
    output_dir: str | Path,
    *,
    variable_name: str = "",
    prefix: str = "",
) -> dict[str, Path]:
    """Export records to CSV files.

    Creates:
    - One chronicle CSV per station (datetime, value)
    - A metadata CSV (station info summary)
    - A table of contents CSV (index of all exported files)

    Returns dict of created file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not records:
        return {}

    pfx = f"{prefix}_" if prefix else ""
    created: dict[str, Path] = {}

    # Per-station chronicle CSVs
    chronicle_rows: list[dict] = []
    for rec in records:
        safe_id = safe_file_token(rec.station_id)
        fname = f"{pfx}{safe_id}_chronicle.csv"
        fpath = output_dir / fname
        rec.data[["datetime", "value"]].to_csv(fpath, index=False)
        created[f"chronicle_{rec.station_id}"] = fpath

        chronicle_rows.append(
            {
                "station_id": rec.station_id,
                "file": fname,
                "variable": rec.variable,
                "source": rec.source,
                "unit": rec.unit,
                "source_unit": rec.source_unit or "",
                "frequency": rec.frequency,
                "n_records": rec.n_records,
                "date_start": rec.date_start,
                "date_end": rec.date_end,
                "is_constant": rec.is_constant,
            }
        )

    # Metadata CSV (station summary with coordinates)
    meta_rows: list[dict] = []
    for rec in records:
        row = {
            "station_id": rec.station_id,
            "variable": rec.variable,
            "source": rec.source,
            "unit": rec.unit,
            "source_unit": rec.source_unit or "",
            "frequency": rec.frequency,
            "n_records": rec.n_records,
            "date_start": rec.date_start,
            "date_end": rec.date_end,
            "is_constant": rec.is_constant,
        }
        if rec.location:
            row["x"] = rec.location.x
            row["y"] = rec.location.y
            row["crs"] = rec.location.crs
            for k, v in rec.location.metadata.items():
                row[k] = v
        meta_rows.append(row)

    meta_path = output_dir / f"{pfx}metadata.csv"
    pd.DataFrame(meta_rows).to_csv(meta_path, index=False)
    created["metadata"] = meta_path

    # Table of contents CSV
    toc_path = output_dir / f"{pfx}table_of_contents.csv"
    pd.DataFrame(chronicle_rows).to_csv(toc_path, index=False)
    created["table_of_contents"] = toc_path

    logger.info("Export: %d chronicles + metadata + TOC -> %s", len(records), output_dir)
    return created
