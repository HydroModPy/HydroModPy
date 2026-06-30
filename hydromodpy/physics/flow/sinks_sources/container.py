"""Top-level container grouping wells, recharge, and ETP payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig
from hydromodpy.physics.flow.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.physics.flow.sinks_sources.lake import FlowLakeConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.flow.sinks_sources.sfr import FlowReachNetworkConfig
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
    lakes : dict[str, FlowLakeConfig]
        Lake / reservoir boundaries keyed by a user-defined string id.
    sfr : dict[str, FlowReachNetworkConfig]
        Streamflow-routing networks keyed by a user-defined string id.
    recharge : FlowRechargeConfig | None
        Diffuse recharge configuration. ``None`` means no recharge.
    etp : FlowEtpConfig | None
        Diffuse evapotranspiration configuration. ``None`` means no
        EVT package is built.
    """

    wells: Annotated[dict[str, FlowWellConfig], Profile.USER] = Field(
        default_factory=dict,
        description="Mapping of well ids to typed well payloads.",
    )
    lakes: Annotated[dict[str, FlowLakeConfig], Profile.USER] = Field(
        default_factory=dict,
        description="Mapping of lake ids to typed lake / reservoir payloads.",
    )
    sfr: Annotated[dict[str, FlowReachNetworkConfig], Profile.USER] = Field(
        default_factory=dict,
        description="Mapping of stream-network ids to typed SFR payloads.",
    )
    flow_barriers: Annotated[dict[str, FlowBarrierConfig], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Mapping of flow-barrier ids to typed HFB payloads (general addon, any "
            "model). A lake's dam cutoff wall is declared on the lake instead."
        ),
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

    @field_validator("lakes", mode="before")
    @classmethod
    def _validate_lakes(cls, value):
        """Normalize and pre-validate the lakes mapping."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.lakes must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            lake_id = str(raw_key).strip()
            if lake_id == "":
                raise ValueError("flow.sinks_sources.lakes cannot contain empty lake ids")
            out[lake_id] = raw_payload
        return out

    @field_validator("sfr", mode="before")
    @classmethod
    def _validate_sfr(cls, value):
        """Normalize and pre-validate the sfr mapping."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.sfr must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            network_id = str(raw_key).strip()
            if network_id == "":
                raise ValueError("flow.sinks_sources.sfr cannot contain empty network ids")
            out[network_id] = raw_payload
        return out

    @field_validator("flow_barriers", mode="before")
    @classmethod
    def _validate_flow_barriers(cls, value):
        """Normalize and pre-validate the flow_barriers mapping."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.flow_barriers must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            barrier_id = str(raw_key).strip()
            if barrier_id == "":
                raise ValueError("flow.sinks_sources.flow_barriers cannot contain empty ids")
            out[barrier_id] = raw_payload
        return out
