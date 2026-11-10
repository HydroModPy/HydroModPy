"""Resolve the DEM raster file from ``[[data.dem.sources]]``.

The geographic delineation pipeline needs a concrete DEM file path before any
data variable runs. A user declares the DEM under ``[[data.dem.sources]]``
(with source = "file", source = "url", or an API provider such as
"ign_geoplateforme_dem").

Resolution order:
- The first source in ``[[data.dem.sources]]`` that yields a valid DEM file wins.
- A ``file`` source resolves ``path`` against the project root.
- A ``url`` source downloads and caches the remote raster.
- An API source (e.g. ``ign_geoplateforme_dem``) uses an outlet-buffer bootstrap
  bounding box (60 km wide around the outlet).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.common.geo_helpers import require_declared_crs
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.source.port import Extent, FetchRequest, fetch_within
from hydromodpy.data.source.registry import build_from_section, data_sources
from hydromodpy.schema.job.inputset import InputState

_BOOTSTRAP_BUFFER_M = 30_000


def resolve_dem(
    cfg: Any,
    *,
    data_dir: Path | str | None = None,
    bounds: Bounds | None = None,
) -> FileRecord | None:
    """Resolve a concrete DEM raster as a :class:`FileRecord` from ``[[data.dem.sources]]``.

    The first declared DEM source that yields a usable raster is returned.
    ``None`` when the configuration declares no source at all: the caller then
    resolves the DEM through the geographic runtime instead. Does not mutate
    the configuration.
    """
    data_cfg = getattr(cfg, "data", None) if not isinstance(cfg, Mapping) else cfg.get("data")
    if data_cfg is None:
        return None
    dem_cfg = (
        getattr(data_cfg, "dem", None) if not isinstance(data_cfg, Mapping) else data_cfg.get("dem")
    )
    if dem_cfg is None:
        return None

    sources = (
        getattr(dem_cfg, "sources", None)
        if not isinstance(dem_cfg, Mapping)
        else dem_cfg.get("sources")
    )
    if not sources:
        return None

    config_dir: Path | None = None
    if hasattr(cfg, "workspace") and getattr(cfg.workspace, "project_root", None):
        config_dir = Path(cfg.workspace.project_root)
    elif isinstance(cfg, Mapping) and cfg.get("workspace", {}).get("project_root"):
        config_dir = Path(cfg["workspace"]["project_root"])
    elif hasattr(cfg, "source_path") and cfg.source_path:
        config_dir = Path(cfg.source_path).resolve().parent
    else:
        config_dir = Path.cwd()

    output_dir = Path(data_dir) / "dem" if data_dir is not None else None

    for source_cfg in sources:
        source_kind = str(
            getattr(source_cfg, "source", "")
            or (source_cfg.get("source", "") if isinstance(source_cfg, Mapping) else "")
        ).strip()

        if source_kind == "file":
            record = _resolve_file_source(source_cfg, config_dir=config_dir, bounds=bounds)
            if record is not None:
                require_dem_crs(record.path)
                return record
        elif source_kind in data_sources.names("dem"):
            record = _resolve_registered_source(
                source_cfg,
                source_kind=source_kind,
                cfg=cfg,
                output_dir=output_dir,
                bounds=bounds,
            )
            if record is not None:
                require_dem_crs(record.path)
                return record

    raise ConfigError("[data.dem.sources] did not resolve to a DEM file.")


def _resolve_file_source(
    source_cfg: Any,
    *,
    config_dir: Path,
    bounds: Bounds | None,
) -> FileRecord | None:
    raw_path = (
        getattr(source_cfg, "path", None)
        if not isinstance(source_cfg, Mapping)
        else source_cfg.get("path")
    )
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (config_dir / candidate).resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"[data.dem] file source path not found: {candidate}")
    if candidate.is_dir():
        from hydromodpy.data.variables.dem.custom import _find_dem_file_in_dir

        candidate = _find_dem_file_in_dir(candidate)
    if bounds is not None:
        bounds.require_path(candidate, why="the DEM the [data.dem.sources] entry names")
    return FileRecord.of(candidate, state=_state_of(source_cfg), origin="file")


def _resolve_registered_source(
    source_cfg: Any,
    *,
    source_kind: str,
    cfg: Any,
    output_dir: Path | None,
    bounds: Bounds | None,
) -> FileRecord:
    if output_dir is None:
        raise ConfigError(
            f"[data.dem] source {source_kind!r} downloads a DEM and has no data folder to put "
            "it in. Run it from a workspace or a project, whose data/ folder holds the cache."
        )
    source_cls = data_sources.get("dem", source_kind)
    source = build_from_section(source_cls, source_cfg)

    selectors = getattr(source, "selectors", ())
    extent: Extent | None = None
    if (
        "extent" in selectors
        or getattr(source, "requires_extent", False)
        or source_kind == "ign_geoplateforme_dem"
    ):
        geo_cfg = (
            getattr(cfg, "geographic", None)
            if not isinstance(cfg, Mapping)
            else cfg.get("geographic")
        )
        catchment = (
            getattr(geo_cfg, "catchment", None)
            if not isinstance(geo_cfg, Mapping)
            else (geo_cfg.get("catchment") if geo_cfg else None)
        )
        x_out = getattr(geo_cfg, "x_outlet", None) or (
            getattr(catchment, "x_outlet", None) if catchment else None
        )
        y_out = getattr(geo_cfg, "y_outlet", None) or (
            getattr(catchment, "y_outlet", None) if catchment else None
        )
        if isinstance(catchment, Mapping):
            x_out = x_out or catchment.get("x_outlet")
            y_out = y_out or catchment.get("y_outlet")
        if x_out is None or y_out is None:
            raise ValueError(
                "DEM API source requires geographic.catchment.x_outlet / y_outlet to build the "
                "download bbox."
            )

        bbox = (
            float(x_out) - _BOOTSTRAP_BUFFER_M,
            float(y_out) - _BOOTSTRAP_BUFFER_M,
            float(x_out) + _BOOTSTRAP_BUFFER_M,
            float(y_out) + _BOOTSTRAP_BUFFER_M,
        )
        dataset = (
            getattr(source_cfg, "dataset", "bd-alti")
            if not isinstance(source_cfg, Mapping)
            else source_cfg.get("dataset", "bd-alti")
        )
        resolution_m = (
            getattr(source_cfg, "resolution_m", None)
            if not isinstance(source_cfg, Mapping)
            else source_cfg.get("resolution_m")
        )
        if dataset == "rge-alti" and resolution_m is not None and float(resolution_m) == 1.0:
            raise ValueError(
                "[data.dem] rge-alti at resolution_m = 1 cannot bootstrap the project: the "
                f"{2 * _BOOTSTRAP_BUFFER_M / 1000:.0f} km box around the outlet would need "
                "billions of pixels. The 1 m grid is for an explicit extent (the "
                "fetch_rge_alti helper or `hmp data get`). Use resolution_m = 5, or give "
                "a file source."
            )
        extent = Extent(xmin=bbox[0], ymin=bbox[1], xmax=bbox[2], ymax=bbox[3], crs="EPSG:2154")

    output_dir.mkdir(parents=True, exist_ok=True)
    request = FetchRequest(
        out_dir=Path(output_dir),
        extent=extent,
        bounds=bounds if bounds is not None else Bounds(),
    )
    result = fetch_within(source, request)
    if not result.files:
        raise ConfigError(f"[data.dem] source {source_kind!r} did not produce any DEM file.")
    record = result.files[0]
    state = "raw" if source_kind != "url" else _state_of(source_cfg)
    return FileRecord(
        record.path,
        record.sha256,
        state=state,
        nodata=record.nodata,
        origin=record.origin,
    )


def _state_of(source_cfg: Any) -> InputState:
    """Read the declared input state of a DEM source, raw when it says none."""
    if isinstance(source_cfg, Mapping):
        value = source_cfg.get("state")
    else:
        value = getattr(source_cfg, "state", None)
    return value if value is not None else "raw"


def require_dem_crs(path: Path | str) -> None:
    """Refuse a DEM raster that declares no CRS, before the terrain tools read it.

    The catchment is cut out of the DEM file before any data variable runs,
    and the terrain engine stops on such a file with no word on the cause.
    Only the formats rasterio opens as a georeferenced grid are looked at;
    any other file is left to the step that reads it.
    """
    path = Path(path)
    if path.suffix.strip().lower() not in (".tif", ".tiff", ".asc") or not path.is_file():
        return
    import rasterio

    try:
        with rasterio.open(str(path)) as src:
            crs = src.crs
    except rasterio.errors.RasterioError:
        return
    require_declared_crs(crs, path=path, variable="dem")
