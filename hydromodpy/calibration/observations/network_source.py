"""Where the mapped stream network of a network criterion comes from.

A ``[calibration.outputs.<name>]`` of ``support = "network"`` names its
observed network one of two ways: the network the data layer already loaded
and clipped to the catchment (``map.complete = "data.hydrography"``), or an
explicit file (``map.complete`` as a path). A network the DEM derives is no
observation, so it is not offered.
:class:`hydromodpy.calibration.config.CalibNetworkMap` holds one field
for it, so exactly one of the two is declared; this module turns that
declaration into geometry, or refuses by naming why it cannot.

The in-memory route never re-clips and never re-derives: the geographic
pipeline already built the network once, at
``run_ctx.state.setup.geographic_features.hydrographic_networks``, and this
module only reads the handle it left there. A file arrives whole.
:func:`cut_to_the_catchment` cuts it with the shape the hydrography data family
clips to, so both routes draw the same map from the same file, and names that
shape, so the heads rule can tell an end the cut made from a head.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError

if TYPE_CHECKING:
    from hydromodpy.solver.base.plan import RunContext

__all__ = [
    "ObservedNetwork",
    "UnresolvedObservedNetwork",
    "cut_to_the_catchment",
    "resolve_network_file",
    "resolve_network_role",
    "resolve_observed_network",
    "unresolved_minimal_observed_networks",
    "unresolved_observed_networks",
]


class UnresolvedObservedNetwork(ConfigError):
    """A network output names a source this project cannot produce a network from.

    Typed apart from every other configuration failure for the same reason as
    :class:`hydromodpy.calibration.parameter_resolution.UnresolvedParameterName`:
    a run refuses it outright, while the preflight collects it beside whatever
    else is wrong with the file.
    """


@dataclass(frozen=True)
class ObservedNetwork:
    """The resolved geometry a network output is scored against, and its provenance.

    ``clipped`` is not a boolean a caller has to infer from ``source``: it is
    what a diagnostic or a report needs printed.
    """

    source: str
    """One of ``"data.hydrography"``, ``"path"``."""

    geometry: Any
    """A GeoDataFrame of lines."""

    crs: str | None
    clipped: bool
    """Whether the geometry was already cut to the delineated catchment."""

    path: str | None
    """The file the geometry was read from, when there was one."""

    cut_outline: Any = None
    """The polygon an end of the map on it was made by, in ``cut_crs``.

    None when every free end of the map is a candidate head: the output keeps
    the map as it arrives, or the run has no catchment to cut it to.
    """

    cut_crs: Any = None
    """The CRS of ``cut_outline``."""


_MISSING_DATA_HYDROGRAPHY = (
    "map.{field} = 'data.hydrography' names a network this project does not load: "
    "declare a source in [[data.hydrography.sources]]."
)


def _hydrographic_network(run_ctx: RunContext, role: str) -> Any:
    """Return the named `HydrographicNetwork` the geographic pipeline attached, or None."""
    features = getattr(run_ctx.state.setup, "geographic_features", None)
    networks = getattr(features, "hydrographic_networks", None)
    return getattr(networks, role, None)


def _checked_lines(geometry: Any, *, source: str, empty_reason: str) -> Any:
    """Refuse an empty or a polygonal resolution; otherwise return its lines.

    A polygon passing this silently turns the observed mask into a surface:
    measured on the Nancon catchment polygon, that marked 105589 of 243552
    cells as observed network rather than the handful its outline crosses.
    """
    if geometry is not None and len(geometry) > 0:
        polygonal = set(geometry.geom_type) & {"Polygon", "MultiPolygon"}
        if polygonal:
            raise UnresolvedObservedNetwork(
                f"{source} resolved to {', '.join(sorted(polygonal))} rather than lines: a "
                "polygon passes silently through the seepage-network mask and the observed "
                "target becomes a surface instead of a stream."
            )
        geometry = geometry[~geometry.geometry.is_empty & ~geometry.geometry.isna()]
    if geometry is None or len(geometry) == 0:
        raise UnresolvedObservedNetwork(f"{source} resolved to no line: {empty_reason}.")
    return geometry


def _network_lines(network: Any, *, source: str, empty_reason: str) -> Any:
    """Read the vector a `HydrographicNetwork` points at and validate it as lines."""
    read_vector = getattr(network, "read_vector", None)
    raw = read_vector() if callable(read_vector) else None
    return _checked_lines(raw, source=source, empty_reason=empty_reason)


def resolve_network_role(
    run_ctx: RunContext,
    role: str,
    *,
    canonical_source: str,
    message_source: str,
    empty_reason: str,
) -> ObservedNetwork | None:
    """Return the `ObservedNetwork` for one `HydrographicNetworks` role, or None.

    Shared by every consumer that reads a network the geographic pipeline
    already attached to the run: clipped to the catchment. Returns None rather than raising when the
    role carries no network, so a caller composes its own refusal message
    around the missing map.
    """
    network = _hydrographic_network(run_ctx, role)
    if network is None:
        return None
    geometry = _network_lines(network, source=message_source, empty_reason=empty_reason)
    return ObservedNetwork(
        source=canonical_source,
        geometry=geometry,
        crs=network.crs,
        clipped=True,
        path=network.vector_path,
    )


def resolve_network_file(path: str, *, message_source: str, empty_reason: str) -> ObservedNetwork:
    """Read a vector file and return it as a path-sourced, unclipped `ObservedNetwork`."""
    import geopandas as gpd

    raw = gpd.read_file(str(path))
    geometry = _checked_lines(raw, source=message_source, empty_reason=empty_reason)
    return ObservedNetwork(
        source="path",
        geometry=geometry,
        crs=str(raw.crs) if raw.crs is not None else None,
        clipped=False,
        path=str(path),
    )


def _from_data_layer(run_ctx: RunContext) -> ObservedNetwork:
    resolved = resolve_network_role(
        run_ctx,
        "reference",
        canonical_source="data.hydrography",
        message_source="map.complete = 'data.hydrography'",
        empty_reason="the network the data layer loaded and clipped to the catchment carries "
        "no feature",
    )
    if resolved is None:
        raise UnresolvedObservedNetwork(_MISSING_DATA_HYDROGRAPHY.format(field="complete"))
    return resolved


def resolve_observed_network(run_ctx: RunContext, output: Any) -> ObservedNetwork:
    """Return the network geometry ``output`` names, or refuse by naming why.

    ``output.map.complete`` holds one source, so the two branches below never
    overlap. Nothing here is written back onto ``output``.
    """
    choice = output.map.complete
    if choice is None:
        raise UnresolvedObservedNetwork(
            "the network output has no complete map. Write map.complete = "
            "'data.hydrography' or the path of a vector file."
        )
    if choice == "data.hydrography":
        return _from_data_layer(run_ctx)
    return resolve_network_file(
        choice,
        message_source=f"map.complete = {str(choice)!r}",
        empty_reason="the file carries no feature",
    )


def _map_mask_file(run_ctx: RunContext) -> Path | None:
    """Return the file a map of this run is cut to, the one the hydrography data family reads.

    ``[data.hydrography] mask_path`` when the file names one, else the watershed the
    geographic step delineated. None when the run wrote neither.
    """
    data = getattr(getattr(run_ctx.state, "cfg", None), "data", None)
    named = getattr(getattr(data, "hydrography", None), "mask_path", None)
    geographic = getattr(run_ctx.state.setup, "geographic", None)
    mask = named or getattr(geographic, "watershed_shp", None)
    if not mask or not Path(str(mask)).exists():
        return None
    return Path(str(mask))


def cut_to_the_catchment(
    run_ctx: RunContext, observed: ObservedNetwork, output: Any
) -> ObservedNetwork:
    """Return the map as the output draws it: cut to the catchment, unless it says otherwise.

    A file is cut by the rule of the hydrography data family, in the CRS of the
    mask. A map the data layer already cut keeps its geometry. Both then name the
    outline, which is what tells an end of the cut from a head
    (:func:`hydromodpy.spatial.geographic.core.network_heads.network_head_candidates`).

    ``map.clip_to_catchment = false`` returns the map as it arrived, and a run with
    no mask has nothing to cut it to. A map with no CRS is left as it is too: the
    projection that follows refuses it by name.
    """
    if not output.map.clip_to_catchment:
        return observed
    mask = _map_mask_file(run_ctx)
    if mask is None or observed.geometry.crs is None:
        return observed
    from hydromodpy.data.variables.hydrography.manager import cut_network, network_mask

    shape, crs = network_mask(mask)
    if observed.clipped:
        return replace(observed, cut_outline=shape, cut_crs=crs)
    frame = cut_network(observed.geometry, shape, crs)
    frame = frame[~frame.geometry.is_empty & ~frame.geometry.isna()]
    if frame.empty:
        raise UnresolvedObservedNetwork(
            f"the map {observed.path!r} holds no line inside the catchment outlined by "
            f"{mask}. Check its CRS, or write map.clip_to_catchment = false to read it whole."
        )
    return replace(
        observed,
        geometry=frame,
        crs=str(crs),
        clipped=True,
        cut_outline=shape,
        cut_crs=crs,
    )


def _refused_declared_source(choice: str, project_config: Any, *, field: str) -> str | None:
    """Return why a statically declared ``choice``, written as ``map.<field>``, cannot resolve."""
    if choice == "data.hydrography":
        hydrography = getattr(getattr(project_config, "data", None), "hydrography", None)
        if hydrography is None or not getattr(hydrography, "sources", None):
            return _MISSING_DATA_HYDROGRAPHY.format(field=field)
        return None
    return None


def _unresolved_networks(calibration: Any, project_config: Any, *, field: str) -> dict[str, str]:
    """Return, per network output, why its statically declared ``map.<field>`` cannot resolve."""
    outputs = getattr(calibration, "outputs", None) or {}
    refused: dict[str, str] = {}
    for name, decl in outputs.items():
        if getattr(decl, "support", None) != "network":
            continue
        choice = getattr(decl.map, field)
        if choice is None:
            continue
        reason = _refused_declared_source(choice, project_config, field=field)
        if reason is not None:
            refused[name] = reason
    return refused


def unresolved_observed_networks(calibration: Any, project_config: Any) -> dict[str, str]:
    """Return, per network output, why its declared source cannot resolve.

    The reporting twin of :func:`resolve_observed_network`, read before a run
    exists: it checks the configuration section a run would need
    populated (``[[data.hydrography.sources]]``) without touching a run context, so it cannot see a source that resolves at
    the file level but produces an empty or a polygonal geometry only once the
    pipeline actually runs. Empty when every declared source resolves.
    """
    return _unresolved_networks(calibration, project_config, field="complete")


def unresolved_minimal_observed_networks(calibration: Any, project_config: Any) -> dict[str, str]:
    """Return, per network output, why its declared minimal source cannot resolve.

    The minimal-map twin of :func:`unresolved_observed_networks`, checking
    ``map.permanent`` instead of ``map.complete``. Only
    ``"data.hydrography"`` is a declared minimal source today, read from the
    same ``[[data.hydrography.sources]]`` section, so it shares
    :func:`_refused_declared_source` unchanged. A missing
    ``reference_permanent`` role on an otherwise loaded source is not seen
    here: that failure needs a run context (:func:`resolve_minimal_network`
    in :mod:`hydromodpy.calibration.observations.observed_network`), since a
    source's permanence coverage is only known once the geographic pipeline
    has read it.
    """
    return _unresolved_networks(calibration, project_config, field="permanent")
