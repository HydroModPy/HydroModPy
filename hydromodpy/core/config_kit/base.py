"""Root Pydantic base class shared by every HydroModPy config model.

All HydroModPy configuration classes inherit from :class:`HydroModelBase`
rather than :class:`pydantic.BaseModel` directly. This centralises the
strictness defaults (``extra="forbid"``, ``validate_assignment=True``)
that the architecture spec (``architecture_cible/02_config_pydantic.md``
§3.1) requires to be uniform across the codebase.

The root base also validates any :class:`VisibleWhen` metadata attached to
fields: a ``VisibleWhen("sibling", ...)`` tag must reference an existing
field on the same model (catches refactor drift).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from hydromodpy.core.config_kit.visible_when import VisibleWhen


class HydroModelBase(BaseModel):
    """Common Pydantic base for every HydroModPy configuration model.

    Sets the strictness defaults required by the architecture spec:

    * ``extra="forbid"`` - typos in TOML keys are rejected.
    * ``validate_assignment=True`` - mutations go through validators.
    * ``str_strip_whitespace=True`` - trims free-form string inputs.
    * ``arbitrary_types_allowed=True`` - needed for pint Quantities and
      other third-party types used in sub-configs.
    * ``ser_json_inf_nan="strings"`` - reproducible JSON even for ``inf``.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
        ser_json_inf_nan="strings",
    )

    @model_validator(mode="after")
    def _check_visible_when_targets(self) -> HydroModelBase:
        own_fields = set(type(self).model_fields)
        for field_name, info in type(self).model_fields.items():
            for meta in info.metadata:
                if isinstance(meta, VisibleWhen) and meta.field not in own_fields:
                    raise ValueError(
                        f"VisibleWhen on {type(self).__name__}.{field_name} "
                        f"references unknown sibling {meta.field!r}"
                    )
        return self

    def to_toml(
        self,
        path: str | Path,
        *,
        profile: Literal["user", "dev", "expert"] = "user",
    ) -> Path:
        """Serialise this config to a TOML file filtered by *profile*.

        Round-trip guarantee: when ``profile="expert"`` is used on a fully
        resolved :class:`~hydromodpy.master_config.hydromodpy_config.HydroModPyConfig`,
        calling :meth:`HydroModPyConfig.from_toml` on the written path yields
        an equivalent config.

        Parameters
        ----------
        path
            Destination TOML file path.
        profile
            One of ``"user"``, ``"dev"``, ``"expert"``. Fields whose
            :class:`~hydromodpy.core.config_kit.profile.Profile` exceeds
            the requested profile are omitted.
        """
        from hydromodpy.core.toml_io.io import dump_toml_with_comments

        return dump_toml_with_comments(self, path, profile=profile)


__all__ = ["HydroModelBase"]
