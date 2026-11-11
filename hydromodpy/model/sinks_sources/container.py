"""Top-level container grouping wells, recharge, and ETP payloads.

``Flow.set_sinks_sources`` reads it. The kinds are wells, recharge, ETP, lakes, SFR networks and
flow barriers, one module each in this folder.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.model.sinks_sources.sfr import FlowReachNetworkConfig
from hydromodpy.model.sinks_sources.wells import FlowWellConfig

_ID_NAMES = {"wells": "well ids", "lakes": "lake ids", "sfr": "network ids", "flow_barriers": "ids"}
"""How the refusal of an empty id names the ids of each table."""

RECHARGE = "recharge"
"""A diffuse recharge is built: the name in ``FlowConfig.active_sinks_sources`` and in ``supports``."""

WELLS = "wells"
"""At least one well is built."""

ETP = "etp"
"""A diffuse evapotranspiration is built."""

FLOW_BARRIERS = "flow_barriers"
"""At least one flow barrier is declared under ``[flow.sinks_sources.flow_barriers]``."""

CUTOFF_WALL = "cutoff_wall"
"""An active lake declares a cutoff wall."""

SINK_SOURCE_TRAITS: frozenset[str] = frozenset({RECHARGE, WELLS, ETP, FLOW_BARRIERS, CUTOFF_WALL})
"""The names a solver backend lists in ``supports`` for the sinks and sources it builds.

A lake and a stream network are boundaries, named once by their boundary id.
"""


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
        description=(
            "Mapping of well ids to typed well payloads. A well declared here is active, "
            "unless it says enabled = false."
        ),
    )
    lakes: Annotated[dict[str, FlowLakeConfig], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Mapping of lake ids to typed lake / reservoir payloads. A lake declared here "
            "is active, unless it says enabled = false. It needs MODFLOW 6."
        ),
    )
    sfr: Annotated[dict[str, FlowReachNetworkConfig], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Mapping of stream-network ids to typed SFR payloads. A network declared here "
            "is active, unless it says enabled = false. It needs MODFLOW 6."
        ),
    )
    flow_barriers: Annotated[dict[str, FlowBarrierConfig], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Mapping of flow-barrier ids to typed HFB payloads (a backend that honors "
            "flow_barriers only). A lake's dam cutoff wall is declared on the lake instead."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
    )
    recharge: Annotated[FlowRechargeConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Diffuse recharge. The table is what activates it, so an empty table takes "
            "its rate from [data.recharge] or the soil section. Absent, the recharge is "
            "zero in every period."
        ),
    )
    etp: Annotated[FlowEtpConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Diffuse evapotranspiration. The table is what activates it, so an empty table "
            "takes its rate from [data.etp]. Absent, no EVT package draws it."
        ),
    )

    def enabled_wells(self) -> dict[str, FlowWellConfig]:
        """Return the wells that are not switched off."""
        return {key: well for key, well in self.wells.items() if well.enabled}

    def enabled_lakes(self) -> dict[str, FlowLakeConfig]:
        """Return the lakes that are not switched off."""
        return {key: lake for key, lake in self.lakes.items() if lake.enabled}

    def enabled_networks(self) -> dict[str, FlowReachNetworkConfig]:
        """Return the stream networks that are not switched off."""
        return {key: network for key, network in self.sfr.items() if network.enabled}

    def enabled_barriers(self) -> dict[str, FlowBarrierConfig]:
        """Return the flow barriers that are not switched off."""
        return {key: barrier for key, barrier in self.flow_barriers.items() if barrier.enabled}

    @field_validator("wells", "lakes", "sfr", "flow_barriers", mode="before")
    @classmethod
    def _validate_id_table(cls, value, info):
        """Normalize one id-keyed table and refuse an empty id."""
        table = info.field_name
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError(f"flow.sinks_sources.{table} must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            entry_id = str(raw_key).strip()
            if entry_id == "":
                raise ValueError(
                    f"flow.sinks_sources.{table} cannot contain empty {_ID_NAMES[table]}"
                )
            out[entry_id] = raw_payload
        return out
