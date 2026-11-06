"""Pydantic configuration model for flow-process definitions.

This module validates and normalizes `[flow]`, `[flow.param.<id>]`, `[flow.ic]`,
`[flow.bc]`, and `[flow.sinks_sources]` payloads from TOML into objects
consumable by `Flow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar

from pydantic import (
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.field_param.config import (
    FieldParamConfig,
    FieldSection,
    FieldVerticalProfileSection,
    resolve_field_param_config_payload,
)
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow import flow_toml_loader
from hydromodpy.physics.flow.boundary_conditions import (
    BCEntry,
    FlowBoundaryConditionConfig,
)
from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialConditions,
    normalize_flow_initial_conditions,
)
from hydromodpy.physics.flow.property_ids import default_unit_of, refusal_of_a_retired_id
from hydromodpy.physics.flow.regime import FlowRegime, normalize_flow_regime
from hydromodpy.physics.flow.runtime_config import FLOW_RUNTIME_KEYS, FlowRuntimeConfig
from hydromodpy.physics.flow.sinks_sources import (
    FlowBarrierConfig,
    FlowLakeConfig,
    FlowSinksSourcesConfig,
    FlowWellConfig,
)

__all__ = [
    "FlowBarrierConfig",
    "FlowBoundaryConditionConfig",
    "FlowConfig",
    "FlowLakeConfig",
    "FlowParam",
    "FlowRuntimeConfig",
    "FlowSinksSourcesConfig",
    "FlowWellConfig",
    "RestartReference",
]


class FlowParam(FieldParamConfig):
    """Flow parameter payload using native field-param sections."""

    field: Annotated[FieldSection, Profile.USER] = Field(
        ...,
        description="Discriminated parameter section `[field]`.",
    )
    field_vertical_profile: Annotated[FieldVerticalProfileSection | None, Profile.USER] = Field(
        default=None,
        description="Optional depth profile section `[field_vertical_profile]`.",
    )

    _base_dir: Path | None = PrivateAttr(default=None)
    _section_label: str = PrivateAttr(default="flow.param")

    def model_post_init(self, context: Any) -> None:
        super().model_post_init(context)
        if isinstance(context, Mapping):
            raw_base_dir = context.get("base_dir")
            if isinstance(raw_base_dir, Path):
                self._base_dir = raw_base_dir
        self._section_label = self._section_label_from_field()

    def _section_label_from_field(self) -> str:
        field_id = self.field.id
        if field_id:
            return f"flow.param.{field_id}"
        return "flow.param"

    def resolved_payload(
        self,
        *,
        param_id: str | None = None,
        base_dir: Path | None = None,
        section_label: str | None = None,
    ) -> dict[str, Any]:
        """Return the resolved runtime field-parameter payload."""
        return resolve_field_param_config_payload(
            self.model_dump(mode="python", exclude_none=True),
            param_id=param_id,
            base_dir=base_dir or self._base_dir,
            section_label=section_label or self._section_label,
        )


class RestartReference(HydroModelBase):
    """The run a hotstart reads, by id and by path: the table form of ``restart_from``.

    The frozen ``config.toml`` of a run writes this form, so a replay finds
    its source by ``sim_id`` in the project it runs in, and by ``path``
    (relative to the project root) elsewhere.
    """

    sim_id: str | None = Field(
        default=None, description="Id of the sealed run whose last heads seed this one"
    )
    path: str | None = Field(
        default=None,
        description="Field store or run directory, relative to the project root or absolute",
    )

    @model_validator(mode="after")
    def _names_something(self) -> RestartReference:
        if not self.sim_id and not self.path:
            raise ValueError("a restart reference names a sim_id, a path, or both")
        return self


class FlowConfig(HydroModelBase):
    """Flow-process configuration.

    Parameters are declared in `param_list` (ordered list of ids), and
    parameter payloads are stored in `param`. A boundary or a sink is active when
    it is declared and does not say ``enabled = false``: :attr:`active_bc` and
    :attr:`active_sinks_sources` read that from the tables, and no list says it.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "active_bc": (
            "a boundary is active when its table is declared. Write [flow.bc.<id>], or "
            "enabled = false in a table to keep it and switch it off."
        ),
        "active_sinks_sources": (
            "a sink or a source is active when its table is declared. Write "
            "[flow.sinks_sources.<name>], or enabled = false in a table to keep it and "
            "switch it off."
        ),
        **{old: f"it moved to [flow.runtime], as {new}." for old, new in FLOW_RUNTIME_KEYS.items()},
    }

    flow_regime: Annotated[FlowRegime, Profile.USER] = Field(
        default="transient",
        description=(
            "Whether the flow is solved as one equilibrium state or through time over "
            "the stress periods of [simulation.time]."
        ),
        examples=["steady", "transient"],
        json_schema_extra=field_metadata(
            widget_type="select",
            unit="-",
            value_docs={
                "steady": (
                    "Solves one equilibrium state, with no storage term: one stress "
                    "period over the whole [simulation.time] window, whatever its "
                    "step_value says, with the forcings averaged over the window."
                ),
                "transient": (
                    "Solves the heads through time; it starts from the state [flow.ic] gives."
                ),
            },
        ),
    )
    first_period_steady: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "For transient flow, mark the first solver stress period as steady-state. "
            "Ignored for steady flow, where all solver periods are steady."
        ),
        examples=[True, False],
        json_schema_extra=field_metadata(
            widget_type="checkbox",
            unit="-",
        ),
    )
    restart_from: Annotated[str | RestartReference | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional hotstart: a prior run whose last time step seeds the initial heads "
            "(and the lake stage), overriding [flow.ic]. Name it by its run name, its sim_id, "
            "the path of its Zarr store, or the table {sim_id, path} the frozen config.toml "
            "of a run writes (the sim_id is looked up first, the path second). The prior "
            "run must share this run's mesh: a regular grid is rebuilt identically and a "
            "generated triangle or voronoi mesh is read back from the mesh cache of "
            "the project; otherwise the cell count differs and restart is refused. None keeps [flow.ic]. "
            "Read only by a solver that declares it can: elsewhere the run is refused "
            "rather than started from [flow.ic] without a word. This is one of the four "
            "ways to say where a transient starts, next to [flow.ic] kind='steady_state' "
            "(equilibrium under the mean recharge, or under a rate you state with "
            "source='prescribed'), kind='custom'/'top'/'bottom' (a level you write), and "
            "`hmp spinup` (repeat a representative window until the state stops moving, "
            "then point this key at its result)."
        ),
    )
    param_list: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered list of the flow parameter ids the run builds, for example "
            "['K', 'Ss', 'Sy']. Each id is described by its [flow.param.<id>] table."
        ),
        examples=[["K", "Sy", "Ss"]],
    )
    param: Annotated[dict[str, FlowParam], Profile.USER] = Field(
        default_factory=dict,
        description="Mapping of flow-parameter identifiers to native FieldParamConfig payloads.",
    )
    bc: Annotated[dict[str, BCEntry], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Mapping of flow boundary-condition payloads parsed from ``[flow.bc]``.\n"
            "\n"
            "**Supported TOML sections**\n"
            "\n"
            "- ``[flow.bc.<id>]``, one block per boundary, keyed by what it is. "
            "Canonical ids: ``drainage``, ``ocean``, ``stream``, ``north_side``, "
            "``south_side``, ``east_side``, ``west_side``\n"
            "- declaring a block is what activates the boundary, and "
            "``enabled = false`` switches it off. An empty block is enough for a "
            "boundary the registry describes entirely, such as a drainage\n"
            "\n"
            "**Common keys**\n"
            "\n"
            "- ``kind``: optional, the registry supplies it: ``dirichlet`` for an "
            "imposed head, ``drain`` for the linear drain ``q = C (h - h_ref)``\n"
            "- ``value``: optional on a drainage, where leaving it out derives the "
            "conductance from K; a head boundary with no value and no forcing "
            "builds no constant head\n"
            "- ``application_domain``: optional, the registry supplies it, and a "
            "value contradicting it is refused\n"
            "\n"
            "**Allowed application_domain values:** ``top``, ``north side``, "
            "``south side``, ``east side``, ``west side``.\n"
            "\n"
            "**Default units:** ``m`` for dirichlet, ``m2/s`` for drain.\n"
            "\n"
            "**The drain under each solver:** the MODFLOW solvers build a ``DRN`` "
            "package. The Boussinesq solver takes its surface closure from "
            "``flow.runtime.surface_interaction_model``."
        ),
    )
    ic: Annotated[FlowInitialConditions, Profile.USER] = Field(
        default_factory=FlowInitialConditions,
        description=(
            "Validated flow initial-condition structure parsed from [flow.ic]. "
            "Stored as FlowInitialConditions(h=FlowInitialCondition)."
        ),
    )
    sinks_sources: Annotated[FlowSinksSourcesConfig, Profile.USER] = Field(
        default_factory=FlowSinksSourcesConfig,
        description="Typed sinks/sources payload (for example pumping wells).",
    )
    runtime: Annotated[FlowRuntimeConfig, Profile.USER] = Field(
        default_factory=FlowRuntimeConfig,
        description=(
            "Settings of the Boussinesq solve: its engine, its surface closure, its "
            "iteration budget and tolerances. The MODFLOW solvers do not read them."
        ),
    )

    @property
    def active_bc(self) -> list[str]:
        """Return the boundaries this run builds: those declared and not switched off.

        'lake' and 'sfr' stand for the tables of ``sinks_sources`` that build a MODFLOW 6
        LAK and SFR package, so only the modflow6 solver takes them.
        """
        active = [bc_id for bc_id, boundary in self.bc.items() if boundary.enabled]
        if self.sinks_sources.enabled_lakes():
            active.append("lake")
        if self.sinks_sources.enabled_networks():
            active.append("sfr")
        return active

    @property
    def active_sinks_sources(self) -> list[str]:
        """Return the sinks and sources this run builds: those declared and not switched off.

        'etp' means three things. Under MODFLOW-NWT the loaded ETP drives the EVT
        package. Under MODFLOW 6 it acts only in soil mode, where it sends the ETP the
        soil left unmet to the EVT package; outside soil mode MODFLOW 6 ignores it and
        says so. Boussinesq rejects it at solver-contract validation.
        """
        tables = self.sinks_sources
        active: list[str] = []
        if tables.recharge is not None and tables.recharge.enabled:
            active.append("recharge")
        if tables.enabled_wells():
            active.append("wells")
        if tables.etp is not None and tables.etp.enabled:
            active.append("etp")
        return active

    @model_validator(mode="before")
    @classmethod
    def _normalize_param_payload_shapes(cls, value):
        """
        Normalize accepted parameter declaration styles before validation.

        Supports canonical shape only, then rewrites to:
        - `param_list`
        - `param`
        """
        if value is None or not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_param_list = payload.get("param_list")
        raw_param = payload.get("param")
        if isinstance(raw_param, Mapping):
            if raw_param_list is None:
                payload["param_list"] = list(raw_param.keys())
        elif raw_param is not None:
            raise ValueError("flow.param must be a mapping payload when provided")

        if payload.get("param_values") is not None:
            raise ValueError("flow.param_values is no longer supported. Use flow.param.")
        return payload

    @field_validator("param_list", mode="before")
    @classmethod
    def _validate_param_list(cls, value):
        """Validate and normalize `flow.param_list` as a unique ordered list."""
        if value is None:
            return []
        if isinstance(value, Mapping):
            value = list(value.keys())
        if not isinstance(value, (list, tuple)):
            raise ValueError("flow.param_list must be a list of parameter ids")

        out: list[str] = []
        for raw_param_id in value:
            param_id = str(raw_param_id).strip()
            if param_id == "":
                raise ValueError("flow.param_list cannot contain empty parameter ids")
            out.append(param_id)
        if len(set(out)) != len(out):
            raise ValueError("flow.param_list cannot contain duplicate parameter ids")
        return out

    @field_validator("param", mode="before")
    @classmethod
    def _validate_param_payloads(cls, value):
        """Normalize `flow.param` payloads into typed FlowParam mappings."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.param must be a mapping of parameter id to payload")

        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            param_id = str(raw_key).strip()
            if param_id == "":
                raise ValueError("flow.param cannot contain empty parameter ids")
            refusal = refusal_of_a_retired_id(param_id)
            if refusal is not None:
                raise ValueError(refusal)
            if isinstance(raw_payload, FlowParam):
                out[param_id] = raw_payload
                continue
            if not isinstance(raw_payload, Mapping):
                raise ValueError(f"flow.param['{param_id}'] must be a mapping payload")
            payload = dict(raw_payload)
            field_payload = payload.get("field")
            if not isinstance(field_payload, Mapping):
                raise KeyError(
                    f"flow.param.{param_id} requires section [flow.param.{param_id}.field]"
                )
            field = dict(field_payload)
            field_id = str(field.get("id", "")).strip()
            if field_id == "":
                field["id"] = param_id
            elif field_id != param_id:
                raise ValueError(
                    f"flow.param.{param_id}.field.id must match section key '{param_id}', "
                    f"got '{field_id}'"
                )
            payload["field"] = field
            out[param_id] = payload
        return out

    @model_validator(mode="after")
    def _validate_param_consistency(self):
        """Enforce cross-field consistency on the flow configuration."""
        missing = [param_id for param_id in self.param_list if param_id not in self.param]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(
                f"flow.param_list declares ids without payload in flow.param: {missing_text}"
            )
        extra = [param_id for param_id in self.param if param_id not in self.param_list]
        if extra:
            extra_text = ", ".join(extra)
            raise ValueError(
                f"flow.param contains ids not declared in flow.param_list: {extra_text}"
            )
        head_ic = getattr(self.ic, "h", None)
        head_ic_kind = str(getattr(head_ic, "kind", "")).strip().lower()
        if head_ic_kind == "steady_state" and self.flow_regime != "transient":
            raise ValueError(
                "flow.ic.kind='steady_state' is only supported when flow.flow_regime='transient'"
            )
        return self

    @field_validator("flow_regime", mode="before")
    @classmethod
    def _validate_flow_regime(cls, value):
        """Validate flow regime enumeration."""
        return normalize_flow_regime(value)

    @field_validator("bc", mode="before")
    @classmethod
    def _validate_bc(cls, value, info: ValidationInfo):
        """Normalize boundary-condition payloads from `[flow.bc]`."""
        context = info.context if isinstance(info.context, Mapping) else {}
        raw_base_dir = context.get("base_dir")
        base_dir = raw_base_dir if isinstance(raw_base_dir, Path) else None
        raw_data_dir = context.get("workspace_data_dir")
        workspace_data_dir = raw_data_dir if isinstance(raw_data_dir, Path) else None
        return flow_toml_loader.normalize_bc_payloads(
            value,
            base_dir=base_dir,
            workspace_data_dir=workspace_data_dir,
        )

    @field_validator("ic", mode="before")
    @classmethod
    def _validate_ic(cls, value):
        """Normalize initial-condition payload from `[flow.ic]`."""
        if value is None:
            return FlowInitialConditions()
        result = normalize_flow_initial_conditions(value, location_prefix="flow.ic")
        if result is None:
            return FlowInitialConditions()
        return result

    @field_validator("sinks_sources", mode="before")
    @classmethod
    def _validate_sinks_sources(cls, value):
        """Normalize sinks/sources payload from `[flow.sinks_sources]`."""
        if value is None:
            return FlowSinksSourcesConfig()
        if isinstance(value, FlowSinksSourcesConfig):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources must be a mapping payload")
        return FlowSinksSourcesConfig.model_validate(dict(value))

    @classmethod
    def _homogeneous_param_entry(cls, param_id: str, value: float) -> dict:
        return {
            "field": {
                "id": param_id,
                "kind": "homogeneous",
                "unit": default_unit_of(param_id),
                "value": float(value),
            }
        }

    @classmethod
    def homogeneous(
        cls,
        *,
        flow_regime: FlowRegime = "transient",
        bc: Mapping[str, object] | None = None,
        sinks_sources: Mapping[str, object] | None = None,
        **parameters: float,
    ) -> FlowConfig:
        """Build a FlowConfig with homogeneous parameters.

        Pass K, Sy, Ss, porosity etc. as keyword arguments. Each becomes a
        homogeneous scalar parameter. Units are inferred from the canonical
        names (K in m/s, Ss in 1/m, Sy dimensionless). *bc* and *sinks_sources* hold
        the tables a TOML file would declare, and what they declare is active.
        """
        if not parameters:
            raise ValueError("homogeneous() requires at least one parameter (e.g. K=5e-5)")
        return cls(
            flow_regime=flow_regime,
            param_list=list(parameters),
            param={pid: cls._homogeneous_param_entry(pid, v) for pid, v in parameters.items()},
            bc=dict(bc or {}),
            sinks_sources=dict(sinks_sources or {}),
        )

    @classmethod
    def steady(cls, **parameters: float) -> FlowConfig:
        """Shortcut for a steady-state FlowConfig with homogeneous parameters."""
        return cls.homogeneous(flow_regime="steady", **parameters)

    @classmethod
    def transient(cls, **parameters: float) -> FlowConfig:
        """Shortcut for a transient FlowConfig with homogeneous parameters."""
        return cls.homogeneous(flow_regime="transient", **parameters)

    @classmethod
    def from_toml_section(
        cls,
        flow_section: Mapping[str, object] | None,
        *,
        base_dir: Path,
        workspace_data_dir: Path | None = None,
    ) -> FlowConfig:
        """Build a validated `FlowConfig` from the `[flow]` TOML section."""
        return flow_toml_loader.from_toml_section(
            cls,
            flow_section,
            base_dir=base_dir,
            workspace_data_dir=workspace_data_dir,
        )
