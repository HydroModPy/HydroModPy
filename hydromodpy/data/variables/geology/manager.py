"""Geology variable manager - standard data-manager pattern.

Caches and serves geology data from the port sources the configuration names,
or from the user's own files. Returns a ``LoadResult`` containing
``FieldRecord`` objects pointing to cached GeoPackage files.

The ``GeologyField`` (field framework) is NOT built here - that
happens in :mod:`hydromodpy.data.loading.loader`, which takes the loaded
geodata and rasterizes it on the domain grid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.state.portable import cache_dir as _hmp_cache_dir
from hydromodpy.data.common.source_extent import resolve_source_extent
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_common import SourceTable
from hydromodpy.data.provenance.derived import custom_derived_dir
from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)
from hydromodpy.data.source.port import FetchRequest


class GeologyManager(SourceTable):
    """Orchestrator for geology data acquisition and caching.

    Follows the standard variable-manager pattern:
    - iterates over configured sources,
    - builds each one through the ``data_sources`` registry,
    - checks catalog cache (bbox-based, no temporal dimension),
    - downloads / loads on miss,
    - registers in SQL catalog with subsumption.
    """

    VARIABLE_NAME = "geology"

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        data_dir: Path | None = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.data_dir = Path(data_dir) if data_dir else None

    def load(self) -> LoadResult:
        """Load geology data from all configured sources."""
        result = LoadResult()
        for source_cfg in self.config.sources:
            records = self._fetch_from_source(source_cfg)
            if not isinstance(records, list):
                records = [records]
            for rec in records:
                if isinstance(rec, FieldRecord):
                    result.fields.append(rec)
                elif rec is not None:
                    result.points.append(rec)
        return result

    # ------------------------------------------------------------------
    # Registered sources
    # ------------------------------------------------------------------

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[FieldRecord]:
        """Fetch the geology of the built source, cache first.

        The catalog is the cache and the source is only asked on a miss. The
        refusals the config model already makes are kept here anyway: a
        duck-typed object that never went through a model reaches this seam on
        the ``hmp data`` path.
        """
        name = str(getattr(source_cfg, "source", "")).strip()
        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        if extent is None:
            raise ValueError(
                f"{name} source requires a bbox (set mask_path, or extent together with a project extent)"
            )
        bbox = extent.to_crs("EPSG:2154").bbox
        force_refresh = getattr(source_cfg, "force_refresh", False)

        if not force_refresh and self.catalog is not None:
            cached = self.catalog.find_cached(
                variable="geology",
                source=name,
                bbox=bbox,
            )
            if cached is not None and cached.file_path not in (SENTINEL_CUSTOM, SENTINEL_EMPTY):
                cached_path = Path(cached.file_path)
                if cached_path.exists():
                    return [
                        FieldRecord(
                            variable="geology",
                            source=name,
                            unit="code",
                            data=cached_path,
                            bbox=bbox,
                            crs="EPSG:2154",
                        )
                    ]

        output_dir = self.data_dir or (_hmp_cache_dir() / "geology")
        result = source.fetch(FetchRequest(out_dir=Path(output_dir), extent=extent))
        gpkg_path = result.files[0].path

        record = FieldRecord(
            variable="geology",
            source=name,
            unit="code",
            data=gpkg_path,
            bbox=bbox,
            crs="EPSG:2154",
        )

        # Register in catalog
        if self.catalog is not None:
            entry_id = self.catalog.register(
                variable="geology",
                source=name,
                file_path=str(gpkg_path),
                bbox=bbox,
                crs="EPSG:2154",
            )
            self.catalog.subsume_entries(
                variable="geology",
                source=name,
                bbox=bbox,
                date_start=None,
                date_end=None,
                exclude_id=entry_id,
            )

        return [record]

    # ------------------------------------------------------------------
    # Custom
    # ------------------------------------------------------------------

    def load_file(self, source_cfg) -> list[FieldRecord]:
        """Load custom geology data (SHP, GPKG, TIF, CSV)."""
        from hydromodpy.data.variables.geology.custom import load_custom_geology

        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        code_field = getattr(source_cfg, "code_field", None)

        records = load_custom_geology(
            source_cfg,
            code_field=code_field,
            bbox=None if extent is None else extent.bbox,
            bbox_crs=None if extent is None else extent.crs,
            derived_dir=custom_derived_dir(self.data_dir, self.VARIABLE_NAME),
        )

        # Register custom entries (never subsumed)
        if self.catalog is not None:
            for rec in records:
                if isinstance(rec, FieldRecord) and isinstance(rec.data, Path):
                    self.catalog.register(
                        variable="geology",
                        source="file",
                        file_path=str(rec.data),
                        bbox=rec.bbox,
                        crs=rec.crs,
                        is_custom=True,
                    )

        return records
