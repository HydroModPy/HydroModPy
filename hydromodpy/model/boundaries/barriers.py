"""Flow barrier traces read from the TOML or a file, and put on a Flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.model.model import Flow

logger = get_logger(__name__)


def _read_barrier_csv(path, where):
    """Read a bare x,y (optionally z) CSV of ordered polyline vertices."""
    import pandas as pd
    from shapely.geometry import LineString

    df = pd.read_csv(path)
    cols = {c.strip().lower(): c for c in df.columns}
    xcol = cols.get("x") or cols.get("lon") or cols.get("easting") or df.columns[0]
    ycol = cols.get("y") or cols.get("lat") or cols.get("northing") or df.columns[1]
    coords = [(float(x), float(y)) for x, y in zip(df[xcol], df[ycol], strict=False)]
    if len(coords) < 2:
        raise ValueError(f"{where} CSV '{path}' needs at least two (x, y) rows.")
    return LineString(coords)


def resolve_barrier_line(cfg: object, *, where: str, project_crs: object = None, data_dir=None):
    """Build the shapely barrier trace from a FlowBarrierConfig.

    Four input formats, so the user can pick whatever they have:
    * inline ``line`` coordinates (a list of (x, y) vertices, multi-segment OK);
    * ``line_path`` to a vector file (.gpkg / .shp / .geojson), reprojected to the
      project CRS and line-merged into a single (possibly multi-vertex) LineString;
    * ``line_path`` to a bare ``.csv`` of ordered x,y (or lon,lat) vertices, taken
      in the project CRS;
    * (``auto`` is handled by the caller, not here).

    A bare ``line_path`` filename resolves against ``<workspace>/data/cutoff_wall/``.
    A genuinely multi-part or non-line geometry raises a typed error naming the file.
    """
    from pathlib import Path

    from shapely.geometry import LineString
    from shapely.ops import linemerge

    line = cfg.get("line") if isinstance(cfg, Mapping) else getattr(cfg, "line", None)
    line_path = (
        cfg.get("line_path") if isinstance(cfg, Mapping) else getattr(cfg, "line_path", None)
    )
    if line:
        return LineString([(float(x), float(y)) for x, y in line])
    if line_path:
        resolved = Path(str(line_path)).expanduser()
        if not resolved.is_absolute() and data_dir is not None:
            from hydromodpy.core.toml_io.paths import resolve_declared_path

            resolved = resolve_declared_path(
                line_path, base_dir=Path(data_dir) / "cutoff_wall", fallback_dirs=[Path(data_dir)]
            )
        if str(resolved).lower().endswith(".csv"):
            return _read_barrier_csv(resolved, where)

        import geopandas as gpd

        gdf = gpd.read_file(str(resolved))
        if gdf.empty:
            raise ValueError(f"{where} line_path '{resolved}' has no geometry.")
        if gdf.crs is None:
            logger.warning(
                "%s line_path '%s' has no CRS; assuming it is already in the project CRS.",
                where,
                resolved,
            )
        elif project_crs is not None:
            gdf = gdf.to_crs(project_crs)
        unioned = gdf.union_all()
        # linemerge stitches a MultiLineString into one; a lone LineString it rejects.
        merged = linemerge(unioned) if unioned.geom_type == "MultiLineString" else unioned
        if isinstance(merged, LineString) and not merged.is_empty:
            return merged
        raise ValueError(
            f"{where} line_path '{resolved}' resolves to a {merged.geom_type}, not a single "
            "LineString; provide one contiguous polyline (a branching or multi-part trace is "
            "not supported)."
        )
    raise ValueError(f"{where} has neither auto, line, nor line_path.")


def apply_flow_barriers_to_flow(*, flow: Flow, project_crs: object = None) -> bool:
    """Resolve the general ``[flow.sinks_sources.flow_barriers]`` traces.

    Each barrier is a :class:`FlowBarrierConfig`. This normalizes the mapping to
    payload dicts ``{'barrier': cfg, 'line': shapely}`` so the HFB builder reads
    the resolved trace and parameters. Idempotent: an already-resolved payload is
    kept as-is. Returns True if at least one barrier line was attached.
    """
    sinks_sources = getattr(flow, "sinks_sources", {})
    barriers = sinks_sources.get("flow_barriers") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(barriers, Mapping) or not barriers:
        return False

    out: dict[str, dict[str, object]] = {}
    attached = False
    for barrier_id, cfg in barriers.items():
        bid = str(barrier_id)
        if isinstance(cfg, Mapping) and "line" in cfg and "barrier" in cfg:
            out[bid] = dict(cfg)
            continue
        line = resolve_barrier_line(
            cfg, where=f"flow.sinks_sources.flow_barriers.{bid}", project_crs=project_crs
        )
        out[bid] = {"barrier": cfg, "line": line}
        attached = True

    if not attached:
        return False
    flow.sinks_sources["flow_barriers"] = out
    return True
