"""Hydrography variable manager: fetch, clip, rasterise.

What this manager needs, and where each piece comes from
--------------------------------------------------------
It used to read a ``geographic`` object for **three** distinct things, only one
of which was an extent: the project CRS, the polygon it clips to, and the
reference grid it rasterises onto. The object is gone and the three are named:

- the clip shape and the request box are one file, ``config.mask_path``, read
  through :func:`~hydromodpy.data.common.source_extent.mask_geometry`;
- the project CRS is **not an input at all** -- the mask says which frame the
  clip happens in, and the network is reprojected into it. On a project run
  that is the same answer, the delineated watershed being written in the
  project CRS; off a project run it is the only answer that means anything,
  because a box and a polygon in two different frames do not intersect;
- the reference grid is ``base_raster``, a constructor argument beside
  ``out_path``, because it is not something a user configures: it is the grid
  the project already has.

**Which CRS the request leaves in is no longer written here either.** The
manager used to compute a WGS84 box, because the three fetch functions it
dispatched to happened to want degrees. It now resolves the source the section
names through :mod:`~hydromodpy.data.source.registry` and reads the CRS off it,
so the literal is gone and a source answering in another frame is asked in that
frame. What stayed is the catalogue: the superset lookup and the registration
are the manager's, because a source knows nothing of DuckDB and must not.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr

from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.source_extent import mask_extent_in, mask_geometry
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.managers.base_manager_common import SourceTable
from hydromodpy.data.source import registry
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN, PERMANENT, UNKNOWN
from hydromodpy.data.variables.hydrography.api_source import (
    NETWORK_PAYLOAD_KIND,
    fetch_network,
    source_from_section,
)
from hydromodpy.data.variables.hydrography.apis.bdtopage import BdTopageSource
from hydromodpy.data.variables.hydrography.apis.euhydro import EuHydroSource
from hydromodpy.data.variables.hydrography.apis.osm import OsmSource
from hydromodpy.data.variables.hydrography.config import (
    HydrographyConfig,
    HydrographySourceConfig,
)
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FILENAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME,
)

if TYPE_CHECKING:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

logger = get_logger(__name__)


class HydrographyManager(SourceTable):
    """Load, clip, and rasterise hydrography vector data."""

    VARIABLE_NAME = "hydrography"
    SOURCES = {
        BdTopageSource.source_id: BdTopageSource,
        EuHydroSource.source_id: EuHydroSource,
        OsmSource.source_id: OsmSource,
    }
    """The built-in network sources. A section may also name one a plugin registered."""

    def __init__(
        self,
        *,
        config: HydrographyConfig,
        out_path: str | Path,
        base_raster: str | Path | None = None,
        catalog: DataCatalogDuckDB | None = None,
        data_dir: Path | None = None,
        stable_folder: str | Path | None = None,
    ) -> None:
        self.config = config
        self._base_raster = base_raster
        from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
        from hydromodpy.spatial.delineation import get_whitebox_backend

        base = Path(stable_folder) if stable_folder else Path(out_path) / PREPROCESSING_DIR
        self._data_folder = base / "hydrography"
        self._data_folder.mkdir(parents=True, exist_ok=True)
        self._backend = get_whitebox_backend()
        self._catalog = catalog
        self._data_dir = data_dir

    def load(self) -> LoadResult:
        """Execute the full pipeline: fetch -> reproject -> clip -> rasterise."""
        # 1. Fetch from each source
        vector_gdfs: list[gpd.GeoDataFrame] = []
        tif_path: Path | None = None

        for src in self.config.sources:
            result = self._fetch_from_source(src)
            if isinstance(result, Path):
                tif_path = result
            elif not result.empty:
                vector_gdfs.append(result)

        # TIF custom shortcut - skip vector pipeline
        if tif_path is not None:
            return self._load_from_tif(tif_path)

        if not vector_gdfs:
            raise ValueError("All hydrography sources returned empty results.")

        # 2. Reproject each source into the frame the mask is in, then clip to its shape.
        # Per source, before the concat: BD Topage answers in Lambert-93, OSM and
        # EU-Hydro in WGS84, and frames in two CRS do not concatenate.
        mask_shape, mask_crs = mask_geometry(self._require_mask_path())
        combined = gpd.GeoDataFrame(
            pd.concat([_in_crs(gdf, mask_crs) for gdf in vector_gdfs], ignore_index=True),
            crs=mask_crs,
        )
        if PERMANENCE_COLUMN in combined.columns:
            # A source that did not say is unknown, never permanent by default.
            combined[PERMANENCE_COLUMN] = combined[PERMANENCE_COLUMN].fillna(UNKNOWN)
        clipped = gpd.clip(combined, mask_shape)

        # 3. Save clipped vector, and its permanent part when the network says which
        streams_path = self._data_folder / HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME
        _write_shapefile(clipped, streams_path)
        permanent_path = self._write_permanent_network(clipped)

        # 4. Rasterise
        rasterize_field = self.config.sources[0].rasterize_field
        tif_out = self._rasterize(streams_path, rasterize_field)

        # 5. Read array
        raster_values = self._read_tif_array(tif_out)

        return self._build_load_result(
            raster_values,
            raster_path=tif_out,
            vector_path=streams_path,
            permanent_vector_path=permanent_path,
        )

    def _write_permanent_network(self, network: gpd.GeoDataFrame) -> Path | None:
        """Write the reaches that flow all year, or remove a stale copy and return None.

        Written only when the network carries the ``permanence`` column. A
        network that does not say which reaches are permanent has no permanent
        part, and a file left by an earlier run on another source would be read
        as if it did.
        """
        path = self._data_folder / HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME
        _remove_shapefile(path)
        if PERMANENCE_COLUMN not in network.columns:
            return None
        lengths_km = network.geometry.length / 1000.0
        by_class = lengths_km.groupby(network[PERMANENCE_COLUMN]).sum().round(1).to_dict()
        logger.info("Hydrography: network length by permanence (km, in the mask CRS): %s", by_class)
        permanent = network[network[PERMANENCE_COLUMN] == PERMANENT]
        if permanent.empty:
            logger.warning(
                "Hydrography: the network says which reaches are permanent and none is; "
                "no permanent network is written."
            )
            return None
        _write_shapefile(permanent, path)
        return path

    # ------------------------------------------------------------------
    # TIF pipeline
    # ------------------------------------------------------------------

    def _load_from_tif(self, tif_path: Path) -> LoadResult:
        """Clip a pre-rasterised TIF to the mask and return the result."""
        from rasterio.mask import mask as rio_mask

        mask_shape, mask_crs = mask_geometry(self._require_mask_path())

        # Reproject the mask geometry into the CRS of the TIF
        with rasterio.open(str(tif_path)) as src:
            tif_crs = src.crs

        mask_gdf = gpd.GeoDataFrame(geometry=[mask_shape], crs=mask_crs)
        if str(mask_crs) != str(tif_crs):
            mask_gdf = mask_gdf.to_crs(tif_crs)

        geom = [mask_gdf.geometry.iloc[0]]

        with rasterio.open(str(tif_path)) as src:
            out_image, out_transform = rio_mask(
                src,
                geom,
                crop=True,
                nodata=-32768,
            )
            out_meta = src.meta.copy()
            out_meta.update(
                height=out_image.shape[1],
                width=out_image.shape[2],
                transform=out_transform,
                nodata=-32768,
            )

        out_tif = self._data_folder / HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FILENAME
        with rasterio.open(str(out_tif), "w", **out_meta) as dst:
            dst.write(out_image)

        arr = out_image[0].astype(float)
        arr[arr < 0] = np.nan

        return self._build_load_result(
            arr,
            raster_path=out_tif,
            vector_path=None,
        )

    def _build_load_result(
        self,
        raster_values: np.ndarray,
        *,
        raster_path: Path,
        vector_path: Path | None,
        permanent_vector_path: Path | None = None,
    ) -> LoadResult:
        """Build the standard hydrography load result."""
        bbox, crs = self._raster_bbox_crs(raster_path)
        data = xr.Dataset(
            data_vars={
                HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME: (
                    ("y", "x"),
                    raster_values,
                )
            }
        )
        record = FieldRecord(
            variable=HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
            source=self.VARIABLE_NAME,
            unit="",
            data=data,
            bbox=bbox,
            crs=crs,
            metadata={
                "raster_path": str(raster_path),
                "vector_path": str(vector_path) if vector_path is not None else None,
                "permanent_vector_path": (
                    str(permanent_vector_path) if permanent_vector_path is not None else None
                ),
                "array_name": HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
            },
        )
        return LoadResult(fields=[record])

    @staticmethod
    def _raster_bbox_crs(raster_path: Path) -> tuple[tuple[float, float, float, float], str]:
        with rasterio.open(str(raster_path)) as ds:
            bounds = ds.bounds
            crs = str(ds.crs) if ds.crs is not None else ""
        return (bounds.left, bounds.bottom, bounds.right, bounds.top), crs

    # ------------------------------------------------------------------
    # Source resolution
    # ------------------------------------------------------------------

    def load_custom(self, source_cfg: HydrographySourceConfig) -> gpd.GeoDataFrame | Path:
        """Load the user's own network file."""
        from hydromodpy.data.variables.hydrography import custom

        return custom.load_custom(source_cfg)

    def _listed_source(self, name: str) -> type:
        """A built-in of ``SOURCES``, or a network source a plugin registered."""
        return registry.get_serving(name, NETWORK_PAYLOAD_KIND)

    def _fetch_listed_source(
        self,
        source_cls: type,
        source_cfg: HydrographySourceConfig,
    ) -> gpd.GeoDataFrame:
        """Ask the source the section names for the box, or reuse the cached network."""
        del source_cls
        source = source_from_section(source_cfg)
        extent = mask_extent_in(self._require_mask_path(), source.extent_crs)

        question = _fetch_question(source)

        if not source_cfg.force_refresh:
            cached = self._try_load_cached(source_cfg.source, extent.bbox, question)
            if cached is not None:
                return cached

        gdf = fetch_network(source, extent)
        self._persist_and_register(gdf, source_cfg.source, extent.bbox, question)

        return gdf

    # ------------------------------------------------------------------
    # Catalog cache helpers
    # ------------------------------------------------------------------

    def _try_load_cached(
        self,
        source: str,
        bbox: tuple[float, float, float, float],
        question: dict[str, object] | None = None,
    ) -> gpd.GeoDataFrame | None:
        """Return cached GeoDataFrame if the catalog has a superset entry.

        *bbox* is the box in the CRS the source declares, and the catalogue
        column carries no CRS of its own. The lookup is keyed on the source as
        well, so one source's entries are all in one frame; two sources in two
        frames never compare their boxes to each other.

        *question* is what the source reports it was asked (the BD Topage
        layer, the OSM waterway types). An entry recorded with another answer
        is a miss: without it, asking BD Topage for its reaches over a box
        where its named rivers were cached served the named rivers. An entry
        recorded before the question was is taken as before.
        """
        if self._catalog is None:
            return None
        entry = self._catalog.find_cached(
            variable=self.VARIABLE_NAME,
            source=source,
            bbox=bbox,
        )
        if entry is None:
            return None
        if not _entry_answers(entry, question):
            logger.debug("Cache entry for hydrography/%s answers another question", source)
            return None
        cached_path = self._catalog.resolve_path(entry.file_path, variable=self.VARIABLE_NAME)
        if not cached_path.exists():
            return None
        logger.debug("Cache hit for hydrography/%s: %s", source, cached_path)
        return gpd.read_file(cached_path)

    def _persist_and_register(
        self,
        gdf: gpd.GeoDataFrame,
        source: str,
        bbox: tuple[float, float, float, float],
        question: dict[str, object] | None = None,
    ) -> None:
        """Save raw API result (EPSG:4326) and register in catalog."""
        if self._catalog is None or self._data_dir is None:
            return
        self._data_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{source}_{_question_digest(question)}" if question else source
        fname = f"{stem}_{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}.gpkg"
        out_path = self._data_dir / fname

        # Ensure EPSG:4326 before persisting
        if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        elif gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")

        gdf.to_file(out_path, driver="GPKG")

        entry_id = self._catalog.register(
            variable=self.VARIABLE_NAME,
            source=source,
            file_path=str(out_path),
            bbox=bbox,
            crs="EPSG:4326",
            is_custom=False,
            fetch_metadata=question or None,
        )
        self._catalog.subsume_entries(
            variable=self.VARIABLE_NAME,
            source=source,
            bbox=bbox,
            date_start=None,
            date_end=None,
            exclude_id=entry_id,
        )

    # ------------------------------------------------------------------
    # Rasterise / read helpers
    # ------------------------------------------------------------------

    def _rasterize(self, streams_path: Path, field: str) -> Path:
        """Rasterise the clipped vector layer using the WhiteBox backend."""
        shp_base = gpd.read_file(streams_path)
        shp_type = shp_base.geometry.type.iloc[0] if not shp_base.empty else "LineString"

        tif_path = self._data_folder / "streams.tif"

        if field not in shp_base.columns:
            logger.debug(
                "Rasterize field %r not found in data; creating synthetic sequential field.",
                field,
            )
            shp_base[field] = range(1, len(shp_base) + 1)
        else:
            try:
                shp_base[field] = pd.to_numeric(shp_base[field])
            except (ValueError, KeyError):
                pass
        _write_shapefile(shp_base, streams_path)

        if self._base_raster is None:
            raise ValueError(
                "Rasterising a hydrography network needs a reference grid; pass "
                "base_raster to HydrographyManager."
            )
        watershed_dem = str(self._base_raster)

        if shp_type in ("MultiPolygon", "Polygon"):
            logger.debug("Rasterising polygon geometry: %s", shp_type)
            self._backend.raster.vector_polygons_to_raster(
                str(streams_path),
                str(tif_path),
                field=field,
                base=watershed_dem,
            )
        elif shp_type in ("MultiLineString", "LineString", "Line"):
            logger.debug("Rasterising line geometry: %s", shp_type)
            self._backend.raster.vector_lines_to_raster(
                str(streams_path),
                str(tif_path),
                field=field,
                base=watershed_dem,
            )
        elif shp_type in ("Point", "MultiPoint"):
            logger.debug("Rasterising point geometry: %s", shp_type)
            self._backend.raster.vector_points_to_raster(
                str(streams_path),
                str(tif_path),
                field=field,
                base=watershed_dem,
            )
        else:
            raise ValueError(f"Unsupported geometry type: {shp_type}")

        self._backend.raster.set_nodata_value(str(tif_path), str(tif_path), back_value=-32768)

        # Also create a point shapefile from the raster (used downstream)
        pt_streams = self._data_folder / "streams_pt.shp"
        self._backend.delineation.raster_to_vector_points(str(tif_path), str(pt_streams))

        return tif_path

    @staticmethod
    def _read_tif_array(tif_path: Path) -> np.ndarray:
        with rasterio.open(str(tif_path)) as ds:
            arr = ds.read(1).astype(float)
        arr[arr < 0] = np.nan
        return arr

    def _require_mask_path(self) -> Path:
        """The one file that says where this request is, or a refusal naming it."""
        mask_path = getattr(self.config, "mask_path", None)
        if not mask_path:
            raise ValueError(
                "Hydrography clips its network to a mask and asks its sources over the "
                "same box; set data.hydrography.mask_path to a SHP/GPKG/GeoJSON/TIF."
            )
        return Path(mask_path)


_SHAPEFILE_SIDECARS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _in_crs(frame: gpd.GeoDataFrame, crs: object) -> gpd.GeoDataFrame:
    """*frame* in *crs*; a frame that declares none is taken as WGS84."""
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    if str(frame.crs) != str(crs):
        frame = frame.to_crs(crs)
    return frame


def _fetch_question(source: object) -> dict[str, object]:
    """What *source* reports it was asked, in the shape the catalogue stores it."""
    metadata = getattr(source, "metadata", None)
    reported = metadata() if callable(metadata) else {}
    return json.loads(json.dumps(reported or {}, sort_keys=True, default=str))


def _entry_answers(entry: object, question: dict[str, object] | None) -> bool:
    """Whether a cached *entry* was fetched for the same *question*."""
    recorded = getattr(entry, "fetch_metadata", None)
    if recorded in (None, "", {}):
        return True
    if isinstance(recorded, str):
        try:
            recorded = json.loads(recorded)
        except ValueError:
            return False
    return recorded == (question or {})


def _question_digest(question: dict[str, object]) -> str:
    """Eight hex digits naming *question* in a cache file name."""
    text = json.dumps(question, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _write_shapefile(frame: gpd.GeoDataFrame, path: Path) -> None:
    """Write *frame* as a shapefile, quiet about the names cut to ten letters.

    BD Topage names run to 33 letters and its dates carry a time; the cut to
    ten letters and the dates stored as text are the shapefile's, and expected.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Column names longer than 10 characters")
        warnings.filterwarnings("ignore", message="Normalized/laundered field name")
        warnings.filterwarnings("ignore", message=".*created as String field")
        frame.to_file(path)


def _remove_shapefile(path: Path) -> None:
    """Delete the shapefile at *path* and every sidecar written with it."""
    for suffix in _SHAPEFILE_SIDECARS:
        path.with_suffix(suffix).unlink(missing_ok=True)
