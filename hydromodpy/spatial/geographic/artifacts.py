"""What a geographic runtime left on disk, read off the runtime itself.

Both geographic runtimes - the delineated :class:`CatchmentDelineation` and the
synthetic one - hydrate the same public attribute names once they have run.
Asking the object rather than rebuilding paths from the config keeps the two on
one answer, and keeps the list honest: a path the runtime names but never wrote
is dropped, because a step declares what it left, not what it could have left.

The declaration covers **every file a rebuild of the step reads**, so a digest
over it changes exactly when what a resume would reuse changes. The files of the
tree are written once, in ``_TREE_FILES``, which the cache check of the pipeline
reads too (:func:`reused_tree_files`). Two of those files are named by no public
attribute and are derived from the two directory attributes that are.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Every file of a geographic tree. The first item locates the file: the
# attribute that names it on GeographicPaths and on the runtimes, or a directory
# attribute and a file name for the two files no attribute names. The second
# item says when a reuse of the tree needs the file: in every tree ("always"),
# with [geographic.river_network] on ("enabled"), with that table's option that
# writes it on as well, or never (None). A reuse checks the network vector
# through the summary's segment count, and ``watershed_buff_shp`` and
# ``box_buff_shp`` are other spellings of two files above that a runtime may
# set; the declaration still covers them when they exist.
_TREE_FILES: tuple[tuple[str | tuple[str, str], str | None], ...] = (
    ("watershed", "always"),
    ("watershed_shp", "always"),
    ("watershed_contour_shp", "always"),
    (("geographic_path", "watershed_buff.shp"), "always"),
    ("watershed_box_shp", "always"),
    ("box_buff", "always"),
    ("watershed_box_buff_dem", "always"),
    ("watershed_box_buff_fill", "always"),
    ("watershed_box_buff_direc", "always"),
    ("watershed_buff_dem", "always"),
    ("watershed_buff_fill", "always"),
    ("watershed_buff_direc", "always"),
    ("watershed_dem", "always"),
    ("watershed_fill", "always"),
    ("watershed_direc", "always"),
    ("watershed_contour_tif", "always"),
    (("correcflow_path", "dem_acc_cells.tif"), "enabled"),
    ("river_streams_tif", "enabled"),
    ("hydrographic_network_generated_summary_json", "enabled"),
    ("river_streams_pruned_tif", "prune_short_streams"),
    ("river_stream_order_strahler_tif", "compute_strahler_order"),
    ("river_stream_link_id_tif", "compute_stream_links"),
    ("hydrographic_network_generated_shp", None),
    ("watershed_buff_shp", None),
    ("box_buff_shp", None),
)

# Attributes of the regional flow-product view. These three rasters are the
# expensive half of a delineation and are what a resume must not recompute.
_FLOW_PRODUCT_ATTRIBUTES = ("correc", "direc", "acc")

# A shapefile is a file only by convention: reopening it needs its sidecars, so
# the declaration names them and a digest covers the whole vector. The flag
# marks the three a reuse needs to reopen the vector. The .prj and .cpg are
# digested when they exist and a reuse does not ask for them.
SHAPEFILE_SIDECARS = (
    (".shp", True),
    (".shx", True),
    (".dbf", True),
    (".prj", False),
    (".cpg", False),
)

DESCRIPTION_FILENAME = "_geographic_cache_manifest.json"


def _tree_file(owner: object, location: str | tuple[str, str]) -> str | Path | None:
    """Return the path one entry of ``_TREE_FILES`` names on *owner*, or None."""
    if isinstance(location, str):
        return getattr(owner, location, None)
    folder = getattr(owner, location[0], None)
    return Path(str(folder)) / location[1] if folder else None


def reused_tree_files(paths: object, river_network: Any) -> list[str | Path]:
    """Return the files of the tree under *paths* that a reuse needs, in table order.

    *river_network* is the ``[geographic.river_network]`` config the tree was
    built with.
    """
    network_on = bool(river_network.enabled)
    return [
        _tree_file(paths, location)
        for location, needed in _TREE_FILES
        if needed == "always"
        or (needed is not None and network_on and bool(getattr(river_network, needed)))
    ]


def _expand(raw: object) -> list[Path]:
    """Return the existing files one declared path stands for."""
    if raw in (None, ""):
        return []
    path = Path(str(raw))
    if path.suffix.lower() == ".shp":
        return [
            sidecar
            for suffix, _ in SHAPEFILE_SIDECARS
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

    for location, _ in _TREE_FILES:
        found.extend(_expand(_tree_file(geographic, location)))

    flow_products = getattr(geographic, "_flow_products", None)
    for name in _FLOW_PRODUCT_ATTRIBUTES:
        found.extend(_expand(getattr(flow_products, name, None)))

    seen: dict[Path, None] = {}
    for path in found:
        seen.setdefault(path, None)
    return tuple(sorted(seen))


__all__ = (
    "DESCRIPTION_FILENAME",
    "SHAPEFILE_SIDECARS",
    "geographic_artifact_paths",
    "reused_tree_files",
)
