"""DEM variable, in the standard variable pattern.

Caches and serves DEM data from the port source the configuration names, or
from the user's own files. Returns a ``LoadResult`` containing ``FieldRecord``
objects pointing to cached GeoTIFF files.

The download itself is the port source ``(dem, ign_geoplateforme_dem)``: this
variable resolves the box, writes the sidecar of the file the source returns
and wraps that file into the ``FieldRecord`` the loader reads. A download
needs the data folder of the call, and is refused without one.
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


class DemVariable(SourceTable):
    """Orchestrator for DEM data acquisition and caching.

    Follows the standard variable pattern:
    - iterates over configured sources,
    - builds each one through the ``data_sources`` registry,
    - downloads / loads on miss,
    - writes the sidecar of the downloaded file.
    """

    VARIABLE_NAME = "dem"
    INTERNAL_UNIT = "m"

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
        """Load DEM data from all configured sources."""
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

    def _resolved_source_values(self, source_cfg: Any) -> dict[str, Any]:
        """What only this variable can compute for the IGN source.

        The resolution the dataset names and the departments the declared
        regions hold are measured here, and the sidecar below keeps the
        same values, so what was recorded is what the source served.
        """
        return {
            "resolution_m": _resolution_for_ign_geoplateforme(source_cfg),
            "file_format": _file_format_for_ign_geoplateforme(source_cfg),
            "departments": _department_codes_for_french_dem_source(source_cfg),
        }

    # ------------------------------------------------------------------
    # Registered sources
    # ------------------------------------------------------------------

    def _fetch_listed_source(self, source: Any, source_cfg: Any) -> list[FieldRecord]:
        """Fetch the DEM of the built source and write its sidecar."""
        name = str(getattr(source_cfg, "source", "")).strip()
        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        if extent is None:
            raise ValueError(
                f"{name} source requires a bbox "
                "(set mask_path, or extent together with a project extent)"
            )
        bbox = extent.to_crs("EPSG:2154").bbox

        dataset = str(getattr(source_cfg, "dataset", "bd-alti") or "bd-alti")
        resolution_m = _resolution_for_ign_geoplateforme(source_cfg)
        file_format = _file_format_for_ign_geoplateforme(source_cfg)
        department_codes = _department_codes_for_french_dem_source(source_cfg)

        if self.data_dir is None:
            raise ConfigError(
                f"[data.dem] source {name!r} downloads a DEM and has no data folder to put it "
                "in. Run it from a workspace or a project, whose data/ folder holds the cache."
            )
        result = source.fetch(FetchRequest(out_dir=self.data_dir, extent=extent))
        tif_path = result.files[0].path

        record = FieldRecord(
            variable="dem",
            source=name,
            unit="m",
            data=tif_path,
            bbox=bbox,
            crs="EPSG:2154",
        )

        if self.index is not None:
            self.index.record(
                tif_path,
                variable="dem",
                source=name,
                bbox=bbox,
                crs="EPSG:2154",
                source_unit=f"{dataset}:{resolution_m:g}m:{file_format}",
                fetch_metadata={
                    "provider": "ign_geoplateforme",
                    "dataset": dataset,
                    "resolution_m": resolution_m,
                    "file_format": file_format,
                    "departments": list(department_codes or []),
                    "regions": list(getattr(source_cfg, "regions", None) or []),
                },
            )

        return [record]

    # ------------------------------------------------------------------
    # The user's own file
    # ------------------------------------------------------------------

    def load_file(self, source_cfg) -> list[FieldRecord]:
        """Load the user's DEM (TIF, ASC, NC) where it lies. It is no row of the cache."""
        from hydromodpy.data.variables.dem.custom import load_custom_dem

        bbox = self._resolve_bbox(source_cfg)

        return load_custom_dem(
            source_cfg,
            bbox=bbox,
            derived_dir=derived.derived_dir(self.data_dir, self.VARIABLE_NAME),
        )

    # ------------------------------------------------------------------
    # Bbox resolution
    # ------------------------------------------------------------------

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        """The request box in the CRS of whatever declared it."""
        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        return None if extent is None else extent.bbox


def _file_format_for_ign_geoplateforme(source_cfg: Any) -> str:
    dataset = str(getattr(source_cfg, "dataset", "bd-alti") or "bd-alti")
    if dataset == "rge-alti":
        # Fetched by extent from WMS-Raster: no archive, no department.
        return "GEOTIFF"
    return str(getattr(source_cfg, "file_format", "ASC") or "ASC").upper()


def _department_codes_for_french_dem_source(source_cfg: Any) -> list[str] | None:
    departments = list(getattr(source_cfg, "departments", None) or [])
    if departments:
        return departments
    if str(getattr(source_cfg, "country", "FR") or "").upper() != "FR":
        return None
    regions = list(getattr(source_cfg, "regions", None) or [])
    if not regions:
        return None
    from hydromodpy.catchment.administrative.france import find_departments_in_regions

    return find_departments_in_regions(regions)


def _resolution_for_ign_geoplateforme(source_cfg: Any) -> float:
    resolution_m = getattr(source_cfg, "resolution_m", None)
    if resolution_m is not None:
        return float(resolution_m)
    dataset = str(getattr(source_cfg, "dataset", "bd-alti") or "bd-alti")
    if dataset == "bd-alti":
        return 25.0
    if dataset == "rge-alti":
        from hydromodpy.data.variables.dem.apis.ign_dem_fr import (
            RGE_ALTI_DEFAULT_RESOLUTION_M,
        )

        return RGE_ALTI_DEFAULT_RESOLUTION_M
    raise ValueError(f"Unsupported assembled IGN DEM dataset: {dataset!r}")
