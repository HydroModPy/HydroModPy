"""Geology variable, in the standard variable pattern.

Caches and serves geology data from the port sources the configuration names,
or from the user's own files. Returns a ``LoadResult`` containing
``FieldRecord`` objects pointing to cached GeoPackage files.

The ``GeologyField`` (field framework) is NOT built here - that
happens in :mod:`hydromodpy.data.loading.loader`, which takes the loaded
geodata and rasterizes it on the domain grid.

A download needs the data folder of the call, and is refused without one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.common.source_extent import resolve_source_extent
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.families.common import SourceTable
from hydromodpy.data.provenance import derived
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.source.port import FetchRequest


class GeologyVariable(SourceTable):
    """Orchestrator for geology data acquisition and caching.

    Follows the standard variable pattern:
    - iterates over configured sources,
    - builds each one through the ``data_sources`` registry,
    - looks up the cached rows (bbox-based, no temporal dimension),
    - downloads / loads on miss,
    - writes the sidecar of the download and subsumes the smaller maps.
    """

    VARIABLE_NAME = "geology"

    def __init__(
        self,
        *,
        config: Any,
        index: CacheIndex | None,
        project_extent: tuple | None = None,
        data_dir: Path | None = None,
    ):
        self.config = config
        self.index = index
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

        The cached rows are the cache and the source is only asked on a miss. The
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

        if not force_refresh and self.index is not None:
            cached = self.index.find("geology", name, bbox=bbox)
            if cached is not None and not self.index.is_stale(cached):
                return [
                    FieldRecord(
                        variable="geology",
                        source=name,
                        unit="code",
                        data=cached.path,
                        bbox=bbox,
                        crs="EPSG:2154",
                    )
                ]

        if self.data_dir is None:
            raise ConfigError(
                f"[data.geology] source {name!r} downloads a map and has no data folder to put "
                "it in. Run it from a workspace or a project, whose data/ folder holds the cache."
            )
        result = source.fetch(FetchRequest(out_dir=self.data_dir, extent=extent))
        gpkg_path = result.files[0].path

        record = FieldRecord(
            variable="geology",
            source=name,
            unit="code",
            data=gpkg_path,
            bbox=bbox,
            crs="EPSG:2154",
        )

        # Write the sidecar, then drop the smaller maps this one contains
        if self.index is not None:
            row = self.index.record(
                gpkg_path,
                variable="geology",
                source=name,
                bbox=bbox,
                crs="EPSG:2154",
            )
            self.index.subsume(row)

        return [record]

    # ------------------------------------------------------------------
    # The user's own file
    # ------------------------------------------------------------------

    def load_file(self, source_cfg) -> list[FieldRecord]:
        """Load the user's geology (SHP, GPKG, TIF, CSV) where it lies. It is no row of the cache."""
        from hydromodpy.data.variables.geology.custom import load_custom_geology

        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        code_field = getattr(source_cfg, "code_field", None)

        return load_custom_geology(
            source_cfg,
            code_field=code_field,
            bbox=None if extent is None else extent.bbox,
            bbox_crs=None if extent is None else extent.crs,
            derived_dir=derived.derived_dir(self.data_dir, self.VARIABLE_NAME),
        )
