"""DataEntry - public view on one row of the input-data cache."""

from __future__ import annotations

from collections.abc import Iterable
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

    def used_by(
        self,
        project_catalogs: Iterable[str | Path] | None = None,
    ) -> list[str]:
        """Return the sim_ids that referenced this entry via the SHA-256 bridge.

        Each path in ``project_catalogs`` points to a project index
        database. The cache DB ATTACHes each catalog
        read-only and joins ``tracked_files.sha256`` with this entry's
        ``checksum``. When ``checksum`` is missing or no catalog is
        provided, the result is an empty list (no false positives).
        """
        if not self.checksum or project_catalogs is None:
            return []
        from hydromodpy.results.catalog.cross_db import entry_used_by

        return entry_used_by(
            self.catalog,
            sha256=self.checksum,
            catalog_paths=[Path(p) for p in project_catalogs],
        )

    def preview(self, n: int = 5) -> pd.DataFrame | None:
        """Return the first ``n`` rows of the underlying file when tabular."""
        try:
            import pandas as pd
        except Exception:
            return None
        if not self.file_path.suffix == ".csv" or not self.file_path.exists():
            return None
        return pd.read_csv(self.file_path, nrows=n)
