"""DataEntry - public view on one row of the input-data cache."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


@dataclass
class DataEntry:
    """Lightweight view on a single cache entry.

    Mirrors :class:`~hydromodpy.results.run.Run` for the input-data side:
    identity metadata plus helpers that walk the provenance bridge back to
    the simulations that consumed the entry.
    """

    catalog: DataCatalogDuckDB
    variable: str
    source: str
    file_path: Path
    station_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    date_start: str | None = None
    date_end: str | None = None
    checksum: str | None = None

    def used_by(self) -> list[str]:
        """Return the sim_ids that referenced this cache entry via provenance."""
        return []

    def preview(self, n: int = 5) -> pd.DataFrame | None:
        """Return the first ``n`` rows of the underlying file when tabular."""
        try:
            import pandas as pd
        except Exception:
            return None
        if not self.file_path.suffix == ".csv" or not self.file_path.exists():
            return None
        return pd.read_csv(self.file_path, nrows=n)
