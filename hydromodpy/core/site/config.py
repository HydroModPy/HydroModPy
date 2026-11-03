"""The ``[site]`` section: which catchment a project models.

A real catchment (``kind`` other than a synthetic domain) is named by a
site, so two projects on the same river recognise each other and an index can
group runs by catchment rather than by project folder. The section is a root
section of the project config, documented by the normal walk of the model.

TOML form::

    [site]
    name = "nancon"  # required, [A-Za-z0-9_]+
    label = "Le Nancon a Lecousse"  # optional, free text
    gauge = "J0014010"  # optional, the station scored by default
    uri = "hubeau:J0014010"  # optional, hubeau:<code> or bdtopage:<code>
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import StationName

SITE_NAME_PATTERN = r"^[A-Za-z0-9_]+$"
"""Grammar of a site name: letters, digits and underscores, case kept.

The dash is reserved: it separates the site from the recipe in a case id
(``<site>-<recipe>``).
"""

SITE_URI_PATTERN = r"^(hubeau|bdtopage):[A-Za-z0-9_-]+$"
"""Grammar of a site URI: a registry prefix, a colon and the code in that registry."""


class SiteConfig(HydroModelBase):
    """The catchment a project models, declared once for every key that needs it."""

    name: Annotated[str, Profile.USER] = Field(
        pattern=SITE_NAME_PATTERN,
        description=(
            "Name of the catchment: letters, digits and underscores, case kept. It is "
            "the identity of the site inside the workspace, the value of the site "
            "column of the index and of every exported table. A real catchment "
            "(geographic.catchment.kind from_outlet_coord, from_polyg_shp or "
            "dem) is refused without it. The dash is reserved: it separates the site "
            "from the recipe in a case id."
        ),
        examples=["nancon"],
    )
    label: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Readable name of the catchment, shown in reports, figure footers and "
            "tables. Free text; unset, the name is shown."
        ),
        examples=["Le Nançon à Lécousse"],
    )
    gauge: Annotated[StationName | None, Profile.USER] = Field(
        default=None,
        description=(
            "Station that measures the catchment, written once for every key that "
            "names it. A station source of [data.hydrometry], [data.recharge] or "
            "[data.runoff] (custom chronicles or hubeau) with no station_ids reads "
            "this station; a station_ids that leaves it out is refused by name. "
            "calibration.observed_station_id and [metrics] station default to it. "
            "Unset, a run that loads exactly one discharge station takes that station "
            "as its gauge and writes it in its manifest."
        ),
        examples=["J0014010"],
    )
    uri: Annotated[str | None, Profile.USER] = Field(
        default=None,
        pattern=SITE_URI_PATTERN,
        description=(
            "Identifier of the catchment in a public registry, written "
            "hubeau:<station code> or bdtopage:<code>. It is the only key that "
            "names the same catchment in two workspaces."
        ),
        examples=["hubeau:J0014010"],
    )


__all__ = ["SITE_NAME_PATTERN", "SITE_URI_PATTERN", "SiteConfig"]
