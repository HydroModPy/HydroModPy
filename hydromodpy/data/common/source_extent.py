"""Where a variable manager gets the box it asks a provider for.

The mechanism this module replaces
----------------------------------
``DemManager`` and ``GeologyManager`` carried the same pair of methods, byte
for byte: a ``_resolve_bbox`` that fell back on ``self.geographic`` when the
source config named no mask, and a ``_resolve_bbox_2154`` that reprojected the
result using the CRS it read off ``geographic.watershed_shp``. Both are gone,
and with them the ``geographic`` parameter of the two managers.

Two things were wrong with that pair, and only the first is the campaign's
subject.

**An extent that comes from an object cannot be asked for from outside.**
``geographic`` is a project-scoped object built by the delineation step; a
capability that has one is a capability that has a workspace. The seam that
replaces it already existed and nobody had named it:
``data/loading/loader.py`` sets ``src.mask_path = Path(geographic.watershed_shp)``
before handing the config to the store, so the path where "the watershed" is a
**file** was already the one a project run took. The two managers read
``self.geographic`` *in addition to* that injection, never instead of it. What
the port calls a mask, the loader was already filling in.

``HydrographyManager`` was the third that read the object, and it needed more
than a box: the project CRS, the polygon it clips to and ``watershed_dem``, the
grid it rasterises onto. It is served here through :func:`mask_geometry`, which
is the same door one level down -- the shape and the box come from one file, so
a mask cannot describe one thing to a clip and another to a request. The
reference grid was never an extent and is now a constructor argument.

**A box without its CRS has to borrow one, and it borrowed the wrong one.**
``_resolve_bbox`` returned four bare floats in whatever CRS the mask file
happened to be in, so ``_resolve_bbox_2154`` had to reopen ``watershed_shp``
to learn what they meant. That is right only while ``mask_path`` *is*
``watershed_shp``, which holds for a project run and for nothing else: point
``mask_path`` at a WGS84 GeoPackage over Rennes while the project runs in
Lambert-93, and ``(-1.7069, 48.1165)`` is read as metres and reprojected from
metres -- it lands at ``-1.36 E, -5.98 S``, in the Gulf of Guinea, and the IGN
request comes back from there. :class:`~hydromodpy.data.source.port.Extent` is
the type that makes that unrepresentable, and it is F5b's, not a new one.

Why ``project_extent`` carries a declared CRS and not a measured one
-------------------------------------------------------------------
``project_extent`` is a bare tuple with no CRS anywhere in its plumbing, and
its value **is not in one CRS**: the site-selection pipeline builds it in
Lambert-93 for the DEM (``workflow/_site_selection_dem.py:350``, and
``_expand_projected_bbox`` adds a margin in metres) and converts it to WGS84
for the observation managers (``_observation_request_bbox_wgs84``, same file,
line 422). So the constant is what the DEM side actually receives, measured on
that path and on the unit tests that pin it --
``tests/unit/data_managers/test_dem_manager.py`` passes ``(650000.0,
6400000.0, 1050000.0, 6650000.0)``, which is Lambert-93 or nothing.

**Geology is served by the same function and by no producer.** Nothing in
``workflow/`` ever hands ``GeologyManager`` a ``project_extent`` that is not
``None``; the branch exists, and today only a caller outside this tree can
take it. The constant is not wrong for geology, it is untested there by the
tree itself, and saying otherwise would be exactly the derivation-nobody-checks
that F5c's declaration tests exist against.

Declaring it is strictly better than what stood here before, where the answer
lived in no file at all. It is not the end state: the end state is a
``project_extent`` that is an :class:`Extent`, and that change touches the
site-selection pipeline, the store and the timeseries managers, none of which
this phase needs. ``test_the_project_extent_crs_matches_what_site_selection_builds``
pins it against ``bbox_for_departments``, and that is **one branch** of
``_dem_request_bbox`` out of four -- the `polygon_file` branch reprojects to
EPSG:2154 explicitly at line 376, and the `outlets` branch is metric by
construction of the delineation, but neither is measured here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.source.port import Extent

PROJECT_EXTENT_CRS = "EPSG:2154"
"""The CRS of the ``project_extent`` tuple as the raster managers receive it.

See the module docstring: the tuple carries no CRS of its own, and the value
here is the one its only producer builds for these managers.
"""


def mask_geometry(path: str | Path) -> tuple[Any, str]:
    """Return a mask's polygon **and the CRS it is in**.

    Vector (``.shp``, ``.gpkg``, ``.geojson``) and raster (``.tif``,
    ``.tiff``), the two families
    :func:`~hydromodpy.data.common.geo_helpers.load_mask_geometry` already
    accepted, and the same geometry each of them gave. A raster still goes
    through the valid-cell hull, because a catchment mask is a rectangle that
    is mostly nodata and its footprint is not its catchment.

    A mask that declares no CRS is **refused**, and that is a rupture worth
    naming. ``numpy_engine.py:536`` writes the delineated watershed without one
    when the DEM declares none, so a project built on a CRS-less DEM reaches
    here. On the IGN and BRGM paths it already failed -- geopandas refuses to
    transform naive geometries, it just said so about an anonymous frame rather
    than about a file. On the ``custom`` path it used to go through, the bbox
    and the raster being in the same unknown frame. One door and one answer is
    worth more than a second path that works only while nobody asks what the
    numbers mean, so the refusal names the file and what to do about it.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Mask file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".shp", ".gpkg", ".geojson"):
        geometry, crs = _vector_geometry(path)
    elif suffix in (".tif", ".tiff"):
        geometry, crs = _raster_geometry(path)
    else:
        raise ValueError(f"Unsupported mask format: {suffix}. Use SHP, GPKG, GeoJSON, or TIF.")

    if crs is None:
        raise DataRequestError(
            f"Mask {path} declares no CRS, so the shape it describes means nothing on its "
            "own. Write the file with a CRS, or name the extent explicitly."
        )
    return geometry, str(crs)


def mask_extent(path: str | Path) -> Extent:
    """Return the bounding box of a mask file and the CRS it is in.

    The box is the bounds of what :func:`mask_geometry` returns: for a vector,
    the bounds of the union of its features, which is ``total_bounds``; for a
    raster, the bounds of the valid-cell hull and **not** the raster footprint.
    The two views share one door so that a mask cannot describe one shape to a
    clip and another box to a request.
    """
    geometry, crs = mask_geometry(path)
    xmin, ymin, xmax, ymax = (float(v) for v in geometry.bounds)
    return Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=crs)


def mask_extent_in(path: str | Path, crs: str) -> Extent:
    """The mask's box expressed in *crs*, measured on the reprojected shape.

    Tighter than ``mask_extent(path).to_crs(crs)``, and not by a rounding
    error: the bounds of a reprojected polygon are the image of its own
    vertices, while the bounds of a reprojected box are the image of a
    rectangle that merely contains it. Measured on a Nancon-sized basin from
    EPSG:2154 to EPSG:4326, the box route is 680 m to 1 030 m wider on each
    side. That width is not free -- the catalog serves a cached download only
    when its entry is a superset of the request, so a box that grew by a
    kilometre stops matching what is already on disk and asks the provider
    again for data it has.

    Use this whenever the shape is in hand. :meth:`Extent.to_crs` remains the
    answer when a box is all there ever was, and it densifies its edges for
    that reason.
    """
    geometry, mask_crs = mask_geometry(path)
    if str(mask_crs) == str(crs):
        xmin, ymin, xmax, ymax = (float(v) for v in geometry.bounds)
        return Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=str(crs))

    import geopandas as gpd

    bounds = gpd.GeoSeries([geometry], crs=mask_crs).to_crs(crs).total_bounds
    xmin, ymin, xmax, ymax = (float(v) for v in bounds)
    return Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=str(crs))


def resolve_source_extent(source_cfg, *, project_extent: tuple | None) -> Extent | None:
    """Resolve the extent one source is asked over, from the config alone.

    ``mask_path`` first, because it is the specific answer and the loader fills
    it in from the delineated watershed; then ``extent`` together with the
    project extent, which is the territory-scale request the site-selection
    pipeline builds. ``None`` when the source names neither, and it is the
    caller that decides whether that is a refusal -- ``custom`` sources load a
    file happily without one.
    """
    mask_path = getattr(source_cfg, "mask_path", None)
    if mask_path:
        return mask_extent(mask_path)
    if getattr(source_cfg, "extent", None) and project_extent:
        xmin, ymin, xmax, ymax = project_extent
        return Extent(
            xmin=xmin,
            ymin=ymin,
            xmax=xmax,
            ymax=ymax,
            crs=PROJECT_EXTENT_CRS,
        )
    return None


def _vector_geometry(path: Path):
    """The union of the features, read once so the shape and the CRS agree."""
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - geopandas is a hard dependency here
        raise ImportError("geopandas required for vector mask. pip install geopandas") from exc
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Empty vector file: {path}")
    union = (
        gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.geometry.unary_union
    )
    return union, gdf.crs


def _raster_geometry(path: Path):
    """The valid cells' hull, not the raster's footprint.

    A catchment mask is ``1`` on the catchment and nodata everywhere else in a
    rectangle sized to the accumulation grid
    (``spatial/terrain/port.py:316``), so its footprint and its catchment are
    not the same box at all -- measured on a 10x10 mask whose valid region is
    the central 4x4, ``(0, 0, 100, 100)`` against ``(30, 30, 70, 70)``. The
    polygonising path this delegates to is the one ``geo_helpers`` already
    used, kept for exactly that reason; what this adds is the CRS beside it.
    """
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - rasterio is a hard dependency here
        raise ImportError("rasterio required for raster mask. pip install rasterio") from exc
    from hydromodpy.data.common.geo_helpers import _load_mask_from_raster

    geometry = _load_mask_from_raster(path)
    with rasterio.open(path) as src:
        crs = src.crs
    return geometry, crs
