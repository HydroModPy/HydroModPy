"""Top-level container grouping wells, recharge, and ETP payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellConfig


class FlowSinksSourcesConfig(HydroModelBase):
    """
    Top-level container for all sink/source elements of the flow process.

    Maps directly to the ``[flow.sinks_sources]`` TOML section. All fields
    are optional so that a minimal ``FlowSinksSourcesConfig()`` (no wells,
    no recharge, no etp) is always valid and represents a passive model.

    Fields
    ------
    wells : dict[str, FlowWellConfig]
        Pumping/injection wells keyed by a user-defined string id.
    recharge : FlowRechargeConfig | None
        Diffuse recharge configuration. ``None`` means no recharge.
    etp : FlowEtpConfig | None
        Diffuse evapotranspiration configuration. ``None`` means no
        EVT package is built.
    """

    model_config = ConfigDict(extra="forbid")

    wells: Annotated[dict[str, FlowWellConfig], Profile.USER] = Field(
        default_factory=dict,
        description="Mapping of well ids to typed well payloads.",
    )
    recharge: Annotated[FlowRechargeConfig | None, Profile.USER] = Field(
        default=None,
        description="Diffuse recharge configuration. None = zero recharge for all periods.",
    )
    etp: Annotated[FlowEtpConfig | None, Profile.USER] = Field(
        default=None,
        description="Diffuse evapotranspiration configuration. None = no EVT package built.",
    )

    @field_validator("wells", mode="before")
    @classmethod
    def _validate_wells(cls, value):
        """Normalize and pre-validate the wells mapping."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.wells must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            well_id = str(raw_key).strip()
            if well_id == "":
                raise ValueError("flow.sinks_sources.wells cannot contain empty well ids")
            out[well_id] = raw_payload
        return out
