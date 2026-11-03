"""The one constructor of a domain geometry.

The setup step of a run, the rebuild of a live project, the domain case and the
``domain-build`` capability all build their ``Domain`` here. The declared
section is copied before its zone ids are armed, so the ``[domain]`` of the
project never carries ``catchment`` and ``geology`` as if the user had written
them. The zones themselves are written later by the binders, from artifacts this
function does not receive.

Declare the zone ids the runtime binders write into the domain registry.

``Domain.set_zone`` refuses any id absent from ``domain.zone_ids``, so every id a
binder targets has to be declared before the domain is built. Two of those ids
are hardcoded in the binders themselves and are therefore not the user's to
declare: ``catchment`` (``apply_catchment_zones_to_domain``) and ``geology``
(``apply_geology_to_domain``). Both binders no-op when their artifact is absent,
so arming an id nothing ends up writing costs nothing.

What is left for ``domain.zone_ids`` after this is what its name says: the
zonations a project declares itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.spatial.domain.depth_model_config import RASTER_DEPTH_MODEL_KINDS
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.surface import Surface

BINDER_ZONE_IDS = ("catchment", "geology")
"""Zone ids the workflow binders write under a fixed name, whatever the config says."""


def arm_runtime_zone_ids(
    domain_cfg: Any,
    requested_support_ids: tuple[str, ...] = (),
) -> Any:
    """Append the binder zone ids and the requested support ids, in place."""
    zone_ids = getattr(domain_cfg, "zone_ids", None)
    if zone_ids is None:
        zone_ids = []
        domain_cfg.zone_ids = zone_ids
    if not isinstance(zone_ids, list):
        zone_ids = list(zone_ids)
        domain_cfg.zone_ids = zone_ids

    declared = {str(item).strip().lower() for item in zone_ids}
    for zone_id in BINDER_ZONE_IDS:
        if zone_id not in declared:
            zone_ids.append(zone_id)
            declared.add(zone_id)

    for support_id in requested_support_ids:
        normalized = str(support_id).strip().lower()
        if normalized in declared:
            continue
        zone_ids.append(str(support_id).strip())
        declared.add(normalized)
    return domain_cfg


def domain_config_for_build(
    config: DomainConfig | Mapping[str, object] | None,
    *,
    zone_ids: Iterable[str] = (),
) -> DomainConfig:
    """Return the armed copy of *config* a domain is built from.

    Separate from :func:`build_domain` because a caller that already holds a
    live domain rebuilds it from the ids that domain ended up with, which it
    can only read off the object it is replacing.
    """
    if config is None:
        section = DomainConfig()
    elif isinstance(config, Mapping):
        section = DomainConfig.model_validate(dict(config))
    elif hasattr(config, "model_copy"):
        # Duck-typed rather than ``isinstance``: what the copy is for is that
        # the arming below never reaches the object the caller holds, and any
        # model that can copy itself satisfies that. ``Domain`` refuses the
        # ones that are not a domain section, where the refusal belongs.
        section = config.model_copy(deep=True)
    else:
        raise TypeError("Domain config must be a DomainConfig instance or a mapping")
    return arm_runtime_zone_ids(section, tuple(str(zone_id) for zone_id in zone_ids))


def build_domain(
    config: DomainConfig | Mapping[str, object] | None,
    *,
    surface_topo: Surface,
    zone_ids: Iterable[str] = (),
    substratum_source: Surface | None = None,
    layer_base_sources: Mapping[str, Surface] | None = None,
    active_cells: np.ndarray | None = None,
) -> Domain:
    """Build the domain geometry *config* defines on *surface_topo*.

    The returned domain carries its vertical extent -- the substratum the
    depth model derives -- and no zone at all. Whoever has the artifacts binds
    them afterwards.

    *substratum_source* is the raster a raster depth model reads, on its own
    grid. *layer_base_sources* holds, by name, the layer bases a layering by
    surfaces reads, on their own grids. *active_cells* narrows the cells that
    raster must cover, for a caller that masks the top rather than clipping it.
    """
    return Domain(
        config=domain_config_for_build(config, zone_ids=zone_ids),
        surface_topo=surface_topo,
        substratum_source=substratum_source,
        layer_base_sources=layer_base_sources,
        active_cells=active_cells,
    )


def read_substratum_source(depth_model: object, data: object | None) -> Surface | None:
    """Read the raster a raster depth model places the substratum from.

    *data* is the ``[data]`` section, and only its ``substratum`` member is read,
    only for a ``raster_substratum`` or ``raster_thickness`` depth model. The raster is read on its own grid, and
    the domain reprojects it onto the top. Any other depth model reads nothing.

    Every caller that builds a domain from a project configuration reads the
    raster here, before the data step: the domain is built during setup.
    """
    kind = getattr(depth_model, "kind", None)
    if kind not in RASTER_DEPTH_MODEL_KINDS:
        return None
    substratum = getattr(data, "substratum", None)
    if substratum is None:
        raise ConfigError(
            f"domain.depth_model kind = {kind!r} reads the raster declared under "
            "[data.substratum], and the configuration declares none."
        )
    source = substratum.sources[0]
    return Surface.from_raster(
        source.path, name="substratum_source", default_crs=source.default_crs
    )


def read_layer_base_sources(layers: object, data: object | None) -> dict[str, Surface]:
    """Read the layer bases a layering by surfaces reads, by name.

    *layers* is the ``[domain.layers]`` table and *data* the ``[data]`` section,
    whose ``layer_base`` member holds one raster per name. Each raster is read
    on its own grid, and the domain reprojects it onto the top. A layering that
    reads no base reads nothing. A name ``[data.layer_base]`` does not declare
    is refused by the config on load, and by the domain otherwise.
    """
    names = tuple(getattr(layers, "base_surface_names", ()) or ())
    layer_base = getattr(data, "layer_base", None)
    declared = {} if layer_base is None else {source.name: source for source in layer_base.sources}
    return {
        name: Surface.from_raster(
            declared[name].path, name=f"{name}_source", default_crs=declared[name].default_crs
        )
        for name in names
        if name in declared
    }


__all__ = [
    "build_domain",
    "domain_config_for_build",
    "read_layer_base_sources",
    "read_substratum_source",
]
