"""The ``[publication]`` section: who made a result and under which licence.

``hmp publish`` copies a run, a session or a project out of the tree and
writes ``PUBLICATION.json`` beside it. The licence, the creators and the
attribution of that copy come from here; ``hmp publish --public`` refuses a
project without a licence.

TOML form::

    [publication]
    license = "etalab-2.0"
    creators = ["A. Author"]
    attribution = "Contains data from Hub'Eau and Meteo-France SIM2."
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class PublicationConfig(HydroModelBase):
    """The licence and the authorship written into every publication."""

    license: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Licence of the published results, as an SPDX identifier or a licence "
            "name (CC-BY-4.0, etalab-2.0). Required by hmp publish --public."
        ),
        examples=["etalab-2.0"],
    )
    creators: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="People or bodies credited as creators of the published results.",
        examples=[["A. Author"]],
    )
    attribution: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribution text the publication carries, for the data it was built on.",
        examples=["Contains data from Hub'Eau."],
    )


__all__ = ["PublicationConfig"]
