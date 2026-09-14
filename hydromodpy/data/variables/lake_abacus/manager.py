"""Lake-abacus variable manager - hand-written table-manager pattern.

Loads and caches stage-volume-area lookup tables from custom files. Returns a
``LoadResult`` whose ``tables`` carry the new :class:`TableRecord` contract;
Path-backed records are registered in the catalog like a custom geology
field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.table import TableRecord


class LakeAbacusManager:
    """Orchestrator for lake-abacus data acquisition and caching."""

    VARIABLE_NAME = "lake_abacus"

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple | None = None,
        data_dir: Path | None = None,
        geographic: Any = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None
        self.geographic = geographic

    def load(self) -> LoadResult:
        """Load lake-abacus data from all configured sources."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            for rec in self._fetch_from_source(source_cfg):
                result.tables.append(rec)
        return result

    def _fetch_from_source(self, source_cfg) -> list[TableRecord]:
        """Dispatch to the right loader based on source type."""
        if source_cfg.source == "custom":
            return self._fetch_custom(source_cfg)
        raise ValueError(f"Unknown lake_abacus source: {source_cfg.source}")

    def _fetch_custom(self, source_cfg) -> list[TableRecord]:
        """Load custom lake-abacus data (CSV, Parquet)."""
        from hydromodpy.data.variables.lake_abacus.custom import load_custom_abacus

        records = load_custom_abacus(source_cfg, data_dir=self.data_dir)

        if self.catalog is not None:
            for rec in records:
                if isinstance(rec.data, Path):
                    self.catalog.register(
                        variable="lake_abacus",
                        source="custom",
                        station_id=rec.table_id,
                        file_path=str(rec.data),
                        unit=rec.unit,
                        is_custom=True,
                    )

        return records
