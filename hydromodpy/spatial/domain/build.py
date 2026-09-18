"""The one constructor of a domain geometry, and its four callers.

``Domain(config=..., surface_topo=...)`` was written out at four sites: the
setup step of a run, the rebuild a second run on a live project triggers, the
domain case script, and the bundle exporter. Three of them deep-copied the
declared section and armed the binder zone ids before constructing, each in
its own spelling, and the fourth armed nothing. A fifth spelling was about to
be added by the ``domain-build`` capability, which is what made the repetition
worth removing rather than worth noting.

What the function owns is small and was never the hard part: a configuration
section is copied before it is armed, because ``arm_runtime_zone_ids`` mutates
what it is given and the declared section belongs to the project, not to the
domain built from it. Getting that wrong leaves a project whose ``[domain]``
carries ``catchment`` and ``geology`` as if the user had written them.

What it deliberately does **not** own is the binders. ``catchment`` and
``geology`` are written into the domain after it exists, from artefacts the
geographic step and the data step produce, and a capability that receives
neither still builds a domain. The zone ids are armed here because they are
the *permission* to write those zones, and the permission is a property of the
configuration; the writing is not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.zone_arming import arm_runtime_zone_ids
from hydromodpy.spatial.surface import Surface


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
) -> Domain:
    """Build the domain geometry *config* defines on *surface_topo*.

    The returned domain carries its vertical extent -- the substratum the
    depth model derives -- and no zone at all. Whoever has the artefacts binds
    them afterwards.
    """
    return Domain(
        config=domain_config_for_build(config, zone_ids=zone_ids),
        surface_topo=surface_topo,
    )


__all__ = ["build_domain", "domain_config_for_build"]
