"""From a ``[[data.hydrography.sources]]`` entry to a river network, once.

What this replaces
------------------
Three independent copies of the same four words. ``manager.py`` dispatched
with an ``if``/``elif`` chain on the three names, each branch importing a
provider function by hand; ``resolver.py`` carried a
tuple of the three names so it could tell an API source from a
local file, and imported the manager's chain to run one; and the config model
carried a ``Literal`` of the same list. Nothing made the three agree, and the
solver registry had already shown what happens when a name exists in two places.

Now the name is resolved by :mod:`hydromodpy.data.source.registry` and the
source is asked through the port, so this module holds no source name at all.
The two callers that used to share the dispatch share this instead, and the
resolver no longer imports the manager to reach a download.

Why the manager still owns the cache
------------------------------------
A source knows nothing of the DuckDB catalog, which is the whole point of the
port, so the superset lookup and the registration stay in the manager around
this call. What moved is only the question "which class, built how".
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import DataCapabilityError, DataProductError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import DataSource, Extent, FetchRequest, fetch_within

if TYPE_CHECKING:
    import geopandas as gpd


NETWORK_PAYLOAD_KIND = "features"
"""What a river network is, as the port names payload shapes."""


def source_from_section(source_cfg: object) -> DataSource:
    """Return the registered source one section names, built from that section.

    The section field a constructor names reaches it and nothing else, which is
    :func:`~hydromodpy.data.source.registry.build_from_section`, and the name is
    resolved within the section the caller serves: a section of hydrography
    reaches the sources registered under ``hydrography`` and no others, so the
    DEM of the ``dem`` section cannot be named here at all. That is what the
    key on the pair ``(section, source_id)`` buys, and it is why the payload
    kind is checked on the declaration rather than at the build seam.

    A section naming a source nobody serves raises
    :class:`~hydromodpy.core.exceptions.DataRequestError` listing what this
    installation does serve, plugins included.

    **A source serving another payload kind is refused on its declaration,
    before it is built.** The adversarial gate of this phase is why: reading
    the kind off the *answer* meant a DEM source named in a hydrography section
    started downloading France-wide archives before anything noticed. The
    configuration model refuses the same thing on the same rule, and this
    check is not redundant with it: the model sees a document, this seam is
    called with duck-typed objects that never went through one.
    """
    source_id = str(getattr(source_cfg, "source", "")).strip()
    source_cls = registry.data_sources.get("hydrography", source_id)
    declared = getattr(source_cls, "payload_kind", None)
    if declared != NETWORK_PAYLOAD_KIND:
        raise DataCapabilityError(
            f"Source {source_id!r} serves a {declared!r} payload, and this section accepts a "
            f"{NETWORK_PAYLOAD_KIND!r} payload. A source of another kind belongs to another "
            "variable, and asking it anyway would contact its provider before the answer "
            "could be refused."
        )
    return registry.build_from_section(source_cls, source_cfg)


def fetch_network(
    source: DataSource, extent: Extent, *, bounds: Bounds | None = None
) -> gpd.GeoDataFrame:
    """Return the linework *source* answers with over *extent*.

    *extent* may be in any CRS: the port converts it into the one the source
    declares, which is what removed the hardcoded WGS84 both callers used to
    pass. *bounds* is the :class:`~hydromodpy.core.runtime.bounds.Bounds` of
    the call: the hosts the source declares are refused, through
    :func:`fetch_within`, before anything connects. Unset, the bounds are
    read off *source* itself when it carries any: the manager hands the
    source built under the bounds of the call down its cache seam, the only
    object that seam receives.

    The scratch a ``FetchRequest`` always carries is made here and owned here,
    on D124's rule, rather than taken from the caller. Both callers used to be
    handed a ``scratch/`` directory that nothing ever emptied -- one inside the
    project's preprocessing tree, one inside the user cache -- and two runs of
    one project shared it. A source of this variable declares it writes nothing
    there anyway, and the conformance suite reads the directory back to check;
    a source that broke that promise would now lose what it wrote, which is the
    right answer for a payload this function refuses.
    """
    with TemporaryDirectory(prefix="hmp-hydrography-") as scratch:
        if bounds is None:
            bounds = getattr(source, "bounds", None)
        request = FetchRequest(
            out_dir=Path(scratch),
            extent=extent,
            bounds=Bounds() if not isinstance(bounds, Bounds) else bounds,
        )
        result = fetch_within(source, request)
    if result.kind != NETWORK_PAYLOAD_KIND or result.features is None:
        raise DataProductError(
            f"Source {result.source_id!r} declares a {NETWORK_PAYLOAD_KIND!r} payload and "
            f"answered with a {result.kind!r} one. The declaration was checked before the "
            "fetch, so this is a source contradicting itself, not a section naming the "
            "wrong source."
        )
    return result.features


__all__ = ["NETWORK_PAYLOAD_KIND", "fetch_network", "source_from_section"]
