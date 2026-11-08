"""``config.resolved.toml``: the whole configuration a run used, and what a replay compares.

``config.toml`` holds what the run was given, and a replay reads that file. The
defaults it left out are read again on the replay, so a default that moves in a
later release would change the replay of every run sealed before it. This file
spells them out, so a replay can tell.

It holds two things. Its body is the configuration with every default written and
with the values a rule derives from the configuration alone: the terrain engine an
unset key takes, ``shoreline_band``, ``hfb_buffer``, the station of the metrics. A
replay computes the same body before anything runs, and :func:`config_drift` names
each key that moved. It is never read back as a configuration: a validator that
tells a written key from its default would answer otherwise, which is why
``config.toml`` stays the file a run replays from.

The table :data:`BUILD_TABLE` holds what only the build can decide, from the data
and the mesh: the injected ETP with its surface, the cell sizes a mesh derives from
the DEM pixel, the gauge a run deduces from its single station. A replay can only
compare it once its own build is done (:func:`build_drift`). What is decided later
still, by the solver adapter, goes to the facts of the run and to
``provenance.json``, block ``solver.options``: the IMS complexity and the XT3D
decision of MODFLOW 6, read back from the model.

The table :data:`~hydromodpy.results.storage.contract.RUN_SEARCH_TABLE` of a run
that came out of a calibration holds the ``[calibration]`` section of its session.
``config.toml`` leaves it out, since a run replays as one solve. What a redraw of its
network criterion reads stays with the run, so a copy of the run needs no session.
"""

from __future__ import annotations

import tempfile
import tomllib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.core.toml_io.paths import assign, portable_declared_path
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.core.tracking import rewrite_input_paths
from hydromodpy.results.metric_rule import MetricRule
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    RUN_SEARCH_TABLE,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

BUILD_TABLE: Final[str] = "resolved_at_build"
"""Table of ``config.resolved.toml`` that holds what the build decided. No config key."""

_NOT_THE_COMPUTATION: Final[tuple[str, ...]] = ("simulation.name", "flow.restart_from")
"""Keys a replay may name otherwise: the run it writes, the same source run by its path."""

_MISSING: Final[object] = object()

# ``[workspace]`` keys the loader resolves to absolute paths of this machine.
# The frozen configuration leaves them out: the project that holds the run is
# the anchor, and the loader rebuilds them from where the file sits.
_WORKSPACE_MACHINE_KEYS = ("project_root", "root", "catalog_path", "data_dir", "runs_dir")


@dataclass(frozen=True, slots=True)
class KeyDrift:
    """One key whose value differs between a sealed document and today's."""

    key: str
    sealed: Any
    effective: Any

    def line(self) -> str:
        """Return the key and both values, for a person."""
        return f"{self.key}: sealed {_shown(self.sealed)}, now {_shown(self.effective)}"

    def record(self) -> dict[str, Any]:
        """Return both values for ``lineage.drift``, a side the document leaves out omitted."""
        values = {"sealed": self.sealed, "effective": self.effective}
        return {name: value for name, value in values.items() if value is not _MISSING}


def _shown(value: Any) -> str:
    return "(not written)" if value is _MISSING else repr(value)


def resolved_config_document(
    config: Any,
    project_root: Path,
    *,
    build: Mapping[str, Any] | None = None,
    search: Mapping[str, Any] | None = None,
) -> str:
    """Return ``config.resolved.toml`` of *config* as TOML text.

    *build* is what the build decided, *search* the section of the calibration the
    run came out of.
    """
    payload = _resolved_payload(config, project_root)
    if build:
        payload[BUILD_TABLE] = dict(build)
    if search:
        payload[RUN_SEARCH_TABLE] = dict(search)
    return dumps(payload)


def resolved_at_build(ctx: WorkflowContext) -> dict[str, Any]:
    """Return what the build of the run decided and the configuration does not say."""
    decided: dict[str, Any] = {}
    etp = _resolved_etp(ctx)
    if etp:
        assign(decided, "flow.sinks_sources.etp", etp)
    sizes = (ctx.setup.mesh_summary or {}).get("sizes")
    if sizes:
        decided["mesh"] = dict(sizes)
    station = _deduced_station(ctx)
    if station is not None:
        assign(decided, "metrics.station", station)
    return decided


def config_drift(
    config: Any,
    run_dir: Path,
    *,
    project_root: Path,
    intended: Iterable[str] = (),
) -> tuple[KeyDrift, ...] | None:
    """Return each key of *config* that differs from what the run at *run_dir* sealed.

    ``None`` when the run sealed no ``config.resolved.toml``. *intended* names the
    dotted paths the caller asked to change: they and what lies below them count
    for no drift. Keys that only name the replay itself are left out, and the
    machine keys are already gone from both sides. An input file is compared by
    nothing here: where a replay finds it is its own affair, and the digests of the
    record say whether it holds the same bytes.
    """
    sealed = _read_sealed(run_dir)
    if sealed is None:
        return None
    sealed.pop(BUILD_TABLE, None)
    sealed.pop(RUN_SEARCH_TABLE, None)
    current = tomllib.loads(dumps(_resolved_payload(config, project_root)))
    for payload in (sealed, current):
        rewrite_input_paths(payload, type(config), lambda marker, _path: marker.role)
    exempt = (*_NOT_THE_COMPUTATION, *intended)
    return tuple(
        drift for drift in _differences(sealed, current) if not _under_any(drift.key, exempt)
    )


def build_drift(source_run: Path, replay_run: Path) -> tuple[KeyDrift, ...]:
    """Return what the build of *replay_run* decided otherwise than *source_run*."""
    source = _read_sealed(source_run)
    replay = _read_sealed(replay_run)
    if source is None or replay is None:
        return ()
    return tuple(_differences(source.get(BUILD_TABLE, {}), replay.get(BUILD_TABLE, {})))


def _read_sealed(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / RUN_RESOLVED_CONFIG_FILENAME
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8"))


def portable_config_payload(
    cfg: Any, staging_dir: Path, project_root: Path, *, written_only: bool
) -> dict[str, Any]:
    """Return *cfg* as the portable mapping a run directory freezes.

    With ``written_only`` only the fields *cfg* was given are kept, so the text
    validates back into a configuration with the same fields set; without it
    every field is there, defaults included. The ``[workspace]`` keys the loader
    resolves on this machine are left out. Every input file the configuration
    names is written in the form that resolves back to it from any copy of the
    workspace (:func:`~hydromodpy.core.toml_io.paths.portable_declared_path`): a
    bare name found in ``data/``, a path relative to the project root, or
    ``../../data/...``. Every other path under the project root is written
    relative to it. A data type with no section stays out of ``data.types``: the
    planner inferred it, a file cannot list it, and a replay infers it again. The
    document is staged in *staging_dir* while it is rendered.
    """
    staged = staging_dir / f".{RUN_CONFIG_FILENAME}.staged"
    cfg.to_toml(staged, profile="expert", written_only=written_only)
    try:
        payload = tomllib.loads(staged.read_text(encoding="utf-8"))
    finally:
        staged.unlink(missing_ok=True)
    root = project_root.resolve()
    data_dir = getattr(getattr(cfg, "workspace", None), "data_dir", None)
    rewrite_input_paths(
        payload,
        type(cfg),
        lambda marker, value: portable_declared_path(
            value, role=marker.role, project_root=root, data_dir=data_dir
        ),
    )
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        for key in _WORKSPACE_MACHINE_KEYS:
            workspace.pop(key, None)
        if not workspace:
            payload.pop("workspace")
    data = payload.get("data")
    if isinstance(data, dict) and "types" in data:
        data["types"] = [name for name in data["types"] if name in data]
    return _relativise(payload, root)


def _resolved_payload(config: Any, project_root: Path) -> dict[str, Any]:
    """Return the whole configuration, portable, with what a rule derives from it."""
    with tempfile.TemporaryDirectory() as staging:
        payload = portable_config_payload(config, Path(staging), project_root, written_only=False)
    for dotted, value in _derived_values(config):
        assign(payload, dotted, value)
    return payload


def _derived_values(config: Any) -> Iterator[tuple[str, Any]]:
    """Yield the keys an unset value resolves to, by the rule the builders apply."""
    from hydromodpy.catchment.terrain import registry as terrain_registry

    yield (
        "geographic.terrain_engine",
        terrain_registry.resolved_engine_id(config.geographic.terrain_engine),
    )
    lake = config.mesh.lake_refinement if config.mesh is not None else None
    if lake is not None:
        yield "mesh.lake_refinement.shoreline_band", lake.resolved_shoreline_band
        yield "mesh.lake_refinement.hfb_buffer", lake.resolved_hfb_buffer
    station = MetricRule.from_config(config).station
    if station is not None:
        yield "metrics.station", station


def _resolved_etp(ctx: WorkflowContext) -> dict[str, Any]:
    """Return what the run holds of its ETP, a table the file may not write.

    The ``Model`` answers once it is built, the ``Flow`` before.
    """
    model = getattr(ctx.setup, "model", None)
    if model is not None:
        etp = model.etp
    else:
        sinks_sources = getattr(ctx.setup.flow, "sinks_sources", None)
        etp = sinks_sources.get("etp") if isinstance(sinks_sources, Mapping) else None
    if etp is None:
        return {}
    declared = getattr(getattr(ctx.cfg.flow, "sinks_sources", None), "etp", None)
    return {
        "injected": declared is None,
        "surface_offset_m": float(etp.surface_offset.to("m").magnitude),
        "surface_reference": (
            "drain elevation" if etp.from_soil_reservoir else "topographic surface"
        ),
        "extinction_depth_m": float(etp.extinction_depth),
        "first_clim": etp.first_clim,
        "spatial_mode": etp.spatial_mode,
        "interpolation_method": etp.interpolation_method,
    }


def _deduced_station(ctx: WorkflowContext) -> str | None:
    """Return the gauge the run deduced, when the configuration names no station."""
    from hydromodpy.data.sites.gauge import gauge_of_run

    if MetricRule.from_config(ctx.cfg).station is not None:
        return None
    return gauge_of_run(ctx.cfg.site, getattr(ctx.loaded_data, "hydrometry", None))


def _differences(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> Iterator[KeyDrift]:
    """Yield each flattened key whose value differs, in key order."""
    before = dict(_flattened(sealed))
    after = dict(_flattened(current))
    for key in sorted({*before, *after}):
        left, right = before.get(key, _MISSING), after.get(key, _MISSING)
        if left != right:
            yield KeyDrift(key, left, right)


def _relativise(payload: Any, project_root: Path) -> Any:
    """Return *payload* with every absolute path under *project_root* made relative."""
    if isinstance(payload, dict):
        return {key: _relativise(value, project_root) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_relativise(item, project_root) for item in payload]
    if (
        isinstance(payload, str)
        and payload.startswith(("/", "\\"))
        or (isinstance(payload, str) and len(payload) > 2 and payload[1] == ":")
    ):
        candidate = Path(payload)
        try:
            return candidate.relative_to(project_root).as_posix()
        except ValueError:
            return payload
    return payload


def _flattened(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(dotted path, leaf)``; a list entry is ``key[i]``, an empty table a leaf."""
    if isinstance(value, Mapping) and value:
        for key, item in value.items():
            yield from _flattened(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, Sequence) and not isinstance(value, str) and value:
        for index, item in enumerate(value):
            yield from _flattened(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _under_any(key: str, paths: Iterable[str]) -> bool:
    return any(key == path or key.startswith((f"{path}.", f"{path}[")) for path in paths)


__all__ = [
    "BUILD_TABLE",
    "KeyDrift",
    "build_drift",
    "config_drift",
    "portable_config_payload",
    "resolved_at_build",
    "resolved_config_document",
]
