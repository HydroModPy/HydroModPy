"""Slim ``[postprocess]`` TOML schema retained for backwards compatibility.

The launcher-managed postprocess workflow has been folded into the pipeline
(steps 8 ``extract``, 9 ``derive``, 10 ``export``). This config now exposes
only the high-level flags users still set in TOML files. Unrecognised keys
are silently accepted to keep legacy projects loadable.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.profile import Profile
from hydromodpy.core.config.base import HydroModelBase


class PostprocessConfig(HydroModelBase):
    """No-op postprocess settings parsed from the ``[postprocess]`` section."""

    model_config = ConfigDict(extra="allow")

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Legacy switch. The pipeline now always runs the extract/derive/"
            "export steps regardless of this flag."
        ),
    )
