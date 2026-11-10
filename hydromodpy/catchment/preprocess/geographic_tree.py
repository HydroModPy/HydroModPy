"""The files one geographic tree holds, declared once for whoever counts or drops them.

Both geographic runtimes - the delineated ``CatchmentDelineation`` and the
synthetic one - hydrate the same public attribute names once they have run.
Asking the object rather than rebuilding paths from the config keeps the two on
one answer, and keeps the list honest: a path the runtime names but never wrote
is dropped, because a step declares what it left, not what it could have left.

The declaration covers every file the step leaves for the steps after it, so
the artifacts of the step and the files a run keeps read one list. Two of those files
are named by no public attribute and are derived from the two directory
attributes that are.
"""

from __future__ import annotations

from pathlib import Path

# Every file of a geographic tree, in declaration order. An entry is the
# attribute that names the file on GeographicPaths and on the runtimes, or a
# directory attribute and a file name for the two files no attribute names.
_TREE_FILES: tuple[str | tuple[str, str], ...] = (
    "watershed",
    "watershed_shp",
    "watershed_contour_shp",
    ("geographic_path", "watershed_buff.shp"),
    "watershed_box_shp",
    "box_buff",
    "watershed_box_buff_dem",
    "watershed_box_buff_fill",
    "watershed_box_buff_direc",
    "watershed_buff_dem",
    "watershed_buff_fill",
    "watershed_buff_direc",
    "watershed_dem",
    "watershed_fill",
    "watershed_direc",
    "watershed_contour_tif",
    ("correcflow_path", "dem_acc_cells.tif"),
    "river_streams_tif",
    "hydrographic_network_generated_summary_json",
    "river_streams_pruned_tif",
    "river_stream_order_strahler_tif",
    "river_stream_link_id_tif",
    "hydrographic_network_generated_shp",
    "watershed_buff_shp",
    "box_buff_shp",
)

# The three regional rasters of the flow-product view.
_FLOW_PRODUCT_ATTRIBUTES = ("correc", "direc", "acc")

# A shapefile is a file only by convention: reopening it needs its sidecars.
SHAPEFILE_SIDECARS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _tree_file(owner: object, location: str | tuple[str, str]) -> str | Path | None:
    """Return the path one entry of ``_TREE_FILES`` names on *owner*, or None."""
    if isinstance(location, str):
        return getattr(owner, location, None)
    folder = getattr(owner, location[0], None)
    return Path(str(folder)) / location[1] if folder else None


def _expand(raw: object) -> list[Path]:
    """Return the existing files one declared path stands for."""
    if raw in (None, ""):
        return []
    path = Path(str(raw))
    if path.suffix.lower() == ".shp":
        return [
            sidecar
            for suffix in SHAPEFILE_SIDECARS
            if (sidecar := path.with_suffix(suffix)).is_file()
        ]
    return [path] if path.is_file() else []


def _provided(flow_products: object) -> bool:
    """True when the corrected DEM is an input the run was handed, not a file it wrote."""
    accumulation = getattr(flow_products, "accumulation", None)
    directions = getattr(accumulation, "directions", None)
    conditioned = getattr(directions, "conditioned_dem", None)
    return getattr(conditioned, "method", None) == "provided"


def geographic_artifact_paths(geographic: object) -> tuple[Path, ...]:
    """Return every file a geographic runtime wrote and still holds, once and in order.

    A ``provided`` conditioned DEM is an input, so its file is not declared as
    written.
    """
    if geographic is None:
        return ()

    found: list[Path] = []
    for location in _TREE_FILES:
        found.extend(_expand(_tree_file(geographic, location)))

    flow_products = getattr(geographic, "_flow_products", None)
    for name in _FLOW_PRODUCT_ATTRIBUTES:
        if name == "correc" and _provided(flow_products):
            continue
        found.extend(_expand(getattr(flow_products, name, None)))

    seen: dict[Path, None] = {}
    for path in found:
        seen.setdefault(path, None)
    return tuple(sorted(seen))


__all__ = ("SHAPEFILE_SIDECARS", "geographic_artifact_paths")
