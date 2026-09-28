"""Where the mapped stream network of a network criterion comes from.

A ``[calibration.outputs.<name>]`` of ``support = "network"`` names its
observed network one of three ways: the network the data layer already loaded
and clipped to the catchment (``observed_network = "data.hydrography"``), the
network the DEM pipeline derived by a drainage-area threshold
(``observed_network = "geographic.river_network"``), or an explicit file
(``stream_geometry_path``). :class:`hydromodpy.calibration.config.CalibOutputNetwork`
guarantees exactly one of the three is declared; this module turns that
declaration into geometry, or refuses by naming why it cannot.

The two in-memory routes never re-clip and never re-derive: the geographic
pipeline already built the network once, at
``run_ctx.state.setup.geographic_features.hydrographic_networks``, and this
module only reads the handle it left there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import RunContext

logger = get_logger(__name__)

__all__ = [
    "ObservedNetwork",
    "UnresolvedObservedNetwork",
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

    ``clipped`` and ``dem_derived`` are not booleans a caller has to infer from
    ``source``: they are what a diagnostic or a report needs printed, and
    keeping them explicit means a fourth source, if one is ever added, cannot
    silently pass as clipped or as DEM-derived by omission.
    """

    source: str
    """One of ``"data.hydrography"``, ``"geographic.river_network"``, ``"path"``."""

    geometry: Any
    """A GeoDataFrame of lines."""

    crs: str | None
    clipped: bool
    """Whether the geometry was already cut to the delineated catchment."""

    dem_derived: bool
    """Whether the geometry was extracted from the DEM the model top samples."""

    path: str | None
    """The file the geometry was read from, when there was one."""


_DEM_DERIVED_WARNED = False


def _warn_dem_derived_once() -> None:
    """Warn, at most once per process, that the observed network is circular.

    K/R shapes where the water table meets the surface, which correlates with
    the drainage area the same DEM accumulation cuts a threshold on: the
    criterion then partly fits a seepage density onto a geomorphological one.
    Not refused, since it is a legitimate experiment on a catchment with no
    mapped network of its own, but worth saying once rather than trusting every
    reader of a result to have re-derived it.
    """
    global _DEM_DERIVED_WARNED
    if _DEM_DERIVED_WARNED:
        return
    _DEM_DERIVED_WARNED = True
    logger.warning(
        "observed_network = 'geographic.river_network': the network this output scores "
        "against is derived from the same DEM the model top is sampled from. The criterion "
        "partly fits a seepage density onto a geomorphological one, which is a legitimate "
        "experiment on an uncharted catchment but not the independent check the paper poses."
    )


_MISSING_DATA_HYDROGRAPHY = (
    "observed_network = 'data.hydrography' names a network this project does not load: "
    "declare a source in [[data.hydrography.sources]]."
)
_MISSING_RIVER_NETWORK = (
    "observed_network = 'geographic.river_network' names a network this project does not "
    "derive: set [geographic.river_network] enabled = true and threshold_area_km2 (or "
    "threshold_cells)."
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
    dem_derived: bool = False,
) -> ObservedNetwork | None:
    """Return the `ObservedNetwork` for one `HydrographicNetworks` role, or None.

    Shared by every consumer that reads a network the geographic pipeline
    already attached to the run: clipped to the catchment, and DEM-derived
    only when the caller says so. Returns None rather than raising when the
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
        dem_derived=dem_derived,
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
        dem_derived=False,
        path=str(path),
    )


def _from_data_layer(run_ctx: RunContext) -> ObservedNetwork:
    resolved = resolve_network_role(
        run_ctx,
        "reference",
        canonical_source="data.hydrography",
        message_source="observed_network = 'data.hydrography'",
        empty_reason="the network the data layer loaded and clipped to the catchment carries "
        "no feature",
    )
    if resolved is None:
        raise UnresolvedObservedNetwork(_MISSING_DATA_HYDROGRAPHY)
    return resolved


def _from_dem(run_ctx: RunContext) -> ObservedNetwork:
    resolved = resolve_network_role(
        run_ctx,
        "generated",
        canonical_source="geographic.river_network",
        message_source="observed_network = 'geographic.river_network'",
        empty_reason="threshold_area_km2 is high enough that no stream survives the cut "
        "(spatial/geographic/core/river_network.py returns none silently); lower it",
        dem_derived=True,
    )
    if resolved is None:
        raise UnresolvedObservedNetwork(_MISSING_RIVER_NETWORK)
    _warn_dem_derived_once()
    return resolved


def _from_path(output: Any) -> ObservedNetwork:
    path = getattr(output, "stream_geometry_path", None)
    if not path:
        raise UnresolvedObservedNetwork(
            "calibration output declares neither 'observed_network' nor "
            "'stream_geometry_path': the mapped network has no source."
        )
    return resolve_network_file(
        path,
        message_source=f"stream_geometry_path = {path!r}",
        empty_reason="the file carries no feature",
    )


def resolve_observed_network(run_ctx: RunContext, output: Any) -> ObservedNetwork:
    """Return the network geometry ``output`` names, or refuse by naming why.

    ``output.observed_network`` and ``output.stream_geometry_path`` are
    mutually exclusive by the time a ``CalibOutputNetwork`` validates, so the
    three branches below never overlap. Nothing here is written back onto
    ``output``: with ``validate_assignment=True`` on the model, writing the
    resolved path into ``stream_geometry_path`` would make the next validation
    see both fields declared and refuse the output it just resolved.
    """
    choice = getattr(output, "observed_network", None)
    if choice == "data.hydrography":
        return _from_data_layer(run_ctx)
    if choice == "geographic.river_network":
        return _from_dem(run_ctx)
    return _from_path(output)


def _refused_declared_source(choice: str, project_config: Any, *, field: str) -> str | None:
    """Return why a statically declared ``choice``, written under ``field``, cannot resolve."""
    if choice == "data.hydrography":
        hydrography = getattr(getattr(project_config, "data", None), "hydrography", None)
        if hydrography is None or not getattr(hydrography, "sources", None):
            return (
                f"{field} = 'data.hydrography' names a network this project does not load: "
                "declare a source in [[data.hydrography.sources]]."
            )
        return None
    if choice == "geographic.river_network":
        river_network = getattr(getattr(project_config, "geographic", None), "river_network", None)
        if not bool(getattr(river_network, "enabled", False)):
            return _MISSING_RIVER_NETWORK
        return None
    return None


def _unresolved_networks(calibration: Any, project_config: Any, *, field: str) -> dict[str, str]:
    """Return, per network output, why its statically declared ``field`` cannot resolve."""
    outputs = getattr(calibration, "outputs", None) or {}
    refused: dict[str, str] = {}
    for name, decl in outputs.items():
        if getattr(decl, "support", None) != "network":
            continue
        choice = getattr(decl, field, None)
        if choice is None:
            continue
        reason = _refused_declared_source(choice, project_config, field=field)
        if reason is not None:
            refused[name] = reason
    return refused


def unresolved_observed_networks(calibration: Any, project_config: Any) -> dict[str, str]:
    """Return, per network output, why its declared source cannot resolve.

    The reporting twin of :func:`resolve_observed_network`, read before a run
    exists: it checks the two configuration sections a run would need
    populated (``[[data.hydrography.sources]]``, ``[geographic.river_network]``)
    without touching a run context, so it cannot see a source that resolves at
    the file level but produces an empty or a polygonal geometry only once the
    pipeline actually runs. Empty when every declared source resolves.
    """
    return _unresolved_networks(calibration, project_config, field="observed_network")


def unresolved_minimal_observed_networks(calibration: Any, project_config: Any) -> dict[str, str]:
    """Return, per network output, why its declared minimal source cannot resolve.

    The minimal-map twin of :func:`unresolved_observed_networks`, checking
    ``minimal_observed_network`` instead of ``observed_network``. Only
    ``"data.hydrography"`` is a declared minimal source today, read from the
    same ``[[data.hydrography.sources]]`` section, so it shares
    :func:`_refused_declared_source` unchanged. A missing
    ``reference_permanent`` role on an otherwise loaded source is not seen
    here: that failure needs a run context (:func:`resolve_minimal_network`
    in :mod:`hydromodpy.calibration.observations.observed_network`), since a
    source's permanence coverage is only known once the geographic pipeline
    has read it.
    """
    return _unresolved_networks(calibration, project_config, field="minimal_observed_network")
