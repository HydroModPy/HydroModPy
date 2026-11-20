"""Flow barrier traces read from config or preloaded objects, and put on a Flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.model.flow import Flow

logger = get_logger(__name__)


def resolve_barrier_line(
    cfg: object,
    *,
    where: str,
    project_crs: object = None,
    line_trace: LineString | None = None,
    data_dir: object = None,
) -> LineString:
    """Build the shapely barrier trace from a FlowBarrierConfig.

    The trace is either:
    * inline ``line`` coordinates (a list of (x, y) vertices);
    * a pre-read ``line_trace`` LineString (passed as an object);
    * (``auto`` is handled by the caller, not here).
    """
    from shapely.geometry import LineString

    line = cfg.get("line") if isinstance(cfg, Mapping) else getattr(cfg, "line", None)
    if line:
        return LineString([(float(x), float(y)) for x, y in line])

    if line_trace is not None:
        if isinstance(line_trace, LineString) and not line_trace.is_empty:
            return line_trace
        raise ValueError(f"{where} line_trace must be a non-empty LineString.")

    line_path = (
        cfg.get("line_path") if isinstance(cfg, Mapping) else getattr(cfg, "line_path", None)
    )
    if line_path:
        raise ValueError(
            f"{where} line_path '{line_path}' must be loaded into a line trace before binding."
        )

    raise ValueError(f"{where} has neither auto, line, nor line_path.")


def apply_flow_barriers_to_flow(
    *,
    flow: Flow,
    project_crs: object = None,
    traces: Mapping[str, LineString] | None = None,
    barrier_traces: Mapping[str, LineString] | None = None,
) -> bool:
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

    resolved_traces = barrier_traces or traces or {}
    out: dict[str, dict[str, object]] = {}
    attached = False
    for barrier_id, cfg in barriers.items():
        bid = str(barrier_id)
        if isinstance(cfg, Mapping) and "line" in cfg and "barrier" in cfg:
            out[bid] = dict(cfg)
            continue
        line_trace = resolved_traces.get(bid)
        line = resolve_barrier_line(
            cfg,
            where=f"flow.sinks_sources.flow_barriers.{bid}",
            project_crs=project_crs,
            line_trace=line_trace,
        )
        out[bid] = {"barrier": cfg, "line": line}
        attached = True

    if not attached:
        return False
    flow.sinks_sources["flow_barriers"] = out
    return True
