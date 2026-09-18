"""What a geographic runtime left on disk, read off the runtime itself.

Both geographic runtimes - the delineated :class:`CatchmentDelineation` and the
synthetic one - hydrate the same public attribute names once they have run.
Asking the object rather than rebuilding paths from the config keeps the two on
one answer, and keeps the list honest: a path the runtime names but never wrote
is dropped, because a step declares what it left, not what it could have left.
"""

from __future__ import annotations

from pathlib import Path

# Public attributes carrying one output file each. ``box_buff`` and
# ``box_buff_shp`` are the two spellings of the buffered box; both runtimes set
# at least one of them.
_FILE_ATTRIBUTES = (
    "watershed",
    "watershed_shp",
    "watershed_buff_shp",
    "watershed_box_shp",
    "box_buff",
    "box_buff_shp",
    "watershed_contour_shp",
    "watershed_dem",
    "watershed_fill",
    "watershed_direc",
    "watershed_buff_dem",
    "watershed_buff_fill",
    "watershed_buff_direc",
    "watershed_box_buff_dem",
    "watershed_box_buff_fill",
    "watershed_box_buff_direc",
    "watershed_contour_tif",
    "river_streams_tif",
    "river_streams_pruned_tif",
    "river_stream_order_strahler_tif",
    "river_stream_link_id_tif",
    "hydrographic_network_generated_shp",
    "hydrographic_network_generated_summary_json",
)

# Attributes of the regional flow-product view. These three rasters are the
# expensive half of a delineation and are what a resume must not recompute.
_FLOW_PRODUCT_ATTRIBUTES = ("correc", "direc", "acc")

# A shapefile is a file only by convention: reopening it needs its sidecars, so
# the declaration names them and a digest covers the whole vector.
_SHAPEFILE_SIDECARS = (".shp", ".shx", ".dbf", ".prj", ".cpg")

DESCRIPTION_FILENAME = "_geographic_cache_manifest.json"


def _expand(raw: object) -> list[Path]:
    """Return the existing files one declared path stands for."""
    if raw in (None, ""):
        return []
    path = Path(str(raw))
    if path.suffix.lower() == ".shp":
        return [
            sidecar
            for suffix in _SHAPEFILE_SIDECARS
            if (sidecar := path.with_suffix(suffix)).is_file()
        ]
    return [path] if path.is_file() else []


def geographic_artifact_paths(geographic: object) -> tuple[Path, ...]:
    """Return every file a geographic runtime wrote and still holds.

    The description document comes first when it exists: it is what tells a
    later process that the tree beside it is complete and whose it is.
    """
    if geographic is None:
        return ()

    found: list[Path] = []
    geographic_path = getattr(geographic, "geographic_path", None)
    if geographic_path:
        found.extend(_expand(Path(str(geographic_path)) / DESCRIPTION_FILENAME))

    for name in _FILE_ATTRIBUTES:
        found.extend(_expand(getattr(geographic, name, None)))

    flow_products = getattr(geographic, "_flow_products", None)
    for name in _FLOW_PRODUCT_ATTRIBUTES:
        found.extend(_expand(getattr(flow_products, name, None)))

    seen: dict[Path, None] = {}
    for path in found:
        seen.setdefault(path, None)
    return tuple(sorted(seen))


__all__ = ("DESCRIPTION_FILENAME", "geographic_artifact_paths")
