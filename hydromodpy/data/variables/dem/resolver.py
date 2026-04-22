"""Bridge between [[data.dem.sources]] and [geographic].dem_init_path.

The geographic delineation pipeline needs a concrete DEM file path before
any data manager runs. Historically users had to provide it via
``[geographic].dem_init_path`` even when their DEM was already declared
under ``[[data.dem.sources]]``. This resolver removes that duplication
by populating ``dem_init_path`` from the data-manager declaration when
the geographic field is left empty.

Resolution order for a single source:

- ``source = "custom"`` → resolve ``path`` against the TOML directory.
- ``source = "ign_bdalti"`` → download the bbox via ``fetch_bdalti``,
  using outlet coordinates + a generous buffer (same logic the overview
  pipeline already used).

The first source that yields a usable path wins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


_API_SOURCES = {"ign_bdalti"}
_BOOTSTRAP_BUFFER_M = 30_000


def resolve_dem_path_from_data_sources(
    cfg: Any,
    *,
    config_path: Path,
    cache_dir: Path | None = None,
) -> Path | None:
    """Return a concrete DEM path derived from ``[[data.dem.sources]]``.

    Returns ``None`` when no usable source is declared. Raises when an API
    source is declared but the outlet coordinates required to build the
    download bbox are missing.

    Parameters
    ----------
    cfg
        Validated ``HydroModPyConfig`` instance.
    config_path
        Absolute path to the TOML file (used to resolve relative paths).
    cache_dir
        Directory where API downloads are cached. Falls back to
        ``~/.cache/hydromodpy/dem`` when not provided.
    """
    data_cfg = getattr(cfg, "data", None)
    if data_cfg is None:
        return None
    dem_cfg = getattr(data_cfg, "dem", None)
    if dem_cfg is None:
        return None

    sources = getattr(dem_cfg, "sources", None) or ()
    config_dir = Path(config_path).resolve().parent

    for source_cfg in sources:
        source_kind = str(getattr(source_cfg, "source", "")).strip()
        if source_kind == "custom":
            resolved = _resolve_custom_path(source_cfg, config_dir)
            if resolved is not None:
                return resolved
        elif source_kind in _API_SOURCES:
            return _bootstrap_api_source(
                source_cfg, cfg=cfg, cache_dir=cache_dir,
            )
    return None


def _resolve_custom_path(source_cfg: Any, config_dir: Path) -> Path | None:
    raw_path = getattr(source_cfg, "path", None)
    if raw_path is None:
        return None
    candidate = Path(str(raw_path)).expanduser()
    if not candidate.is_absolute():
        candidate = (config_dir / candidate).resolve()
    if not candidate.exists():
        raise FileNotFoundError(
            f"[data.dem] custom source path not found: {candidate}"
        )
    if candidate.is_dir():
        from hydromodpy.data.variables.dem.custom import _find_dem_file_in_dir

        candidate = _find_dem_file_in_dir(candidate)
    return candidate


def _bootstrap_api_source(
    source_cfg: Any,
    *,
    cfg: Any,
    cache_dir: Path | None,
) -> Path:
    geo_cfg = cfg.geographic
    x_out = getattr(geo_cfg, "x_outlet", None)
    y_out = getattr(geo_cfg, "y_outlet", None)
    if x_out is None or y_out is None:
        raise ValueError(
            "DEM API source requires geographic.x_outlet / y_outlet to "
            "build the download bbox."
        )

    bbox = (
        x_out - _BOOTSTRAP_BUFFER_M,
        y_out - _BOOTSTRAP_BUFFER_M,
        x_out + _BOOTSTRAP_BUFFER_M,
        y_out + _BOOTSTRAP_BUFFER_M,
    )

    from hydromodpy.data.variables.dem.apis.ign_bdalti import fetch_bdalti

    output_dir = cache_dir or (Path.home() / ".cache" / "hydromodpy" / "dem")
    output_dir.mkdir(parents=True, exist_ok=True)
    return fetch_bdalti(output_dir=output_dir, bbox=bbox)
