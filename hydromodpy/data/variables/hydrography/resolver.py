"""Bridge between ``[[data.hydrography.sources]]`` and the map the alpha diagnostic reads.

Twin of :mod:`~hydromodpy.data.variables.dem.resolver`, on the linework instead
of the elevation. The alpha diagnostic runs inside the geographic step, before
any data manager, so it cannot read what ``LoadDataStep`` later produces: it
needs a concrete vector file on disk. The map is named once, under
``[[data.hydrography.sources]]``, and this resolver hands its path to the step.

The map is a diagnostic input and never a model input, so only a local file is
read:

- ``source = "custom"`` resolves ``path`` against the TOML directory, picking the
  first vector file when it points at a directory. A raster is skipped: alpha
  rasterizes geometries onto the DEM grid itself and has nothing to do with an
  already gridded network.
- any other source is a registered API one. It is never downloaded here: the
  watershed it would be clipped against does not exist yet at this point of the
  pipeline, and a regional download for a diagnostic costs more than it tells.
  One ``info`` line says alpha needs a custom vector source.

The first source that yields a usable path wins, and ``None`` means alpha does
not run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def resolve_network_map_path(cfg: Any, *, config_path: Path) -> Path | None:
    """Return the local vector file of ``[[data.hydrography.sources]]``, or None."""

    data_cfg = getattr(cfg, "data", None)
    if data_cfg is None:
        return None
    hydrography_cfg = getattr(data_cfg, "hydrography", None)
    if hydrography_cfg is None:
        return None

    sources = getattr(hydrography_cfg, "sources", None) or ()
    config_dir = Path(config_path).resolve().parent

    for source_cfg in sources:
        source_kind = str(getattr(source_cfg, "source", "")).strip()
        if source_kind == "custom":
            resolved = _resolve_custom_path(source_cfg, config_dir)
            if resolved is not None:
                return resolved
        else:
            logger.info(
                "[data.hydrography] source %r is an API source: the alpha diagnostic "
                "needs a custom vector source and does not download one.",
                source_kind,
            )
    return None


def _resolve_custom_path(source_cfg: Any, config_dir: Path) -> Path | None:
    """Return the vector file a ``custom`` source declares, or None when it holds a raster."""
    raw_path = getattr(source_cfg, "path", None)
    if raw_path is None:
        return None
    candidate = Path(str(raw_path)).expanduser()
    if not candidate.is_absolute():
        candidate = (config_dir / candidate).resolve()
    if not candidate.exists():
        logger.warning(
            "[data.hydrography] custom source path not found: %s. The alpha diagnostic is skipped.",
            candidate,
        )
        return None
    if candidate.is_dir():
        candidate = _find_vector_file_in_dir(candidate)
        if candidate is None:
            return None
    if candidate.suffix.lower() in (".tif", ".tiff"):
        logger.info(
            "[data.hydrography] custom source %s is a raster, so the alpha diagnostic, "
            "which rasterizes geometries onto the DEM grid itself, skips it.",
            candidate,
        )
        return None
    return candidate


def _find_vector_file_in_dir(directory: Path) -> Path | None:
    """Return the first vector file of ``directory``, scaffold templates excluded.

    Deliberately not :func:`~hydromodpy.data.variables.hydrography.custom.load_custom`'s
    scan, which prefers a raster over a vector: alpha needs the linework.
    """
    from hydromodpy.data.common.io_helpers import is_scaffold_example
    from hydromodpy.data.variables.hydrography.custom import _VECTOR_EXTENSIONS

    for extension in _VECTOR_EXTENSIONS:
        for found in sorted(directory.glob(extension)):
            if not is_scaffold_example(found):
                return found
    return None
