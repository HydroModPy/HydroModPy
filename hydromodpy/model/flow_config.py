"""Pydantic configuration model for flow-process definitions.

This module validates and normalizes `[flow]`, `[flow.param.<id>]`, `[flow.ic]`,
`[flow.bc]`, and `[flow.sinks_sources]` payloads from TOML into objects
consumable by `Flow`. The loader at the top of the module reads the raw `[flow]`
table before validation: it canonicalizes the boundary ids and resolves the CSV
paths of the forcings.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, TypeVar

from pydantic import (
    BaseModel,
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
from hydromodpy.core.toml_io.paths import resolve_declared_path
from hydromodpy.model.boundaries.boundary_condition_registry import (
    FLOW_BC_IDS,
    FLOW_BC_KINDS,
    FLOW_BOUNDARY_DEFINITIONS,
    FlowBcId,
)
from hydromodpy.model.boundaries.boundary_conditions import BCEntry, FlowBoundaryConditionConfig
from hydromodpy.model.initial_config import FlowInitialConditions, normalize_flow_initial_conditions
from hydromodpy.model.properties.property_ids import default_unit_of, refusal_of_a_retired_id
from hydromodpy.model.sinks_sources.container import (
    ETP,
    RECHARGE,
    WELLS,
    FlowSinksSourcesConfig,
)
from hydromodpy.model.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.model.sinks_sources.wells import FlowWellConfig
from hydromodpy.model.time.regime import FlowRegime, normalize_flow_regime
from hydromodpy.schema.changes import prerelease_refusal

FLOW_RUNTIME_KEYS: dict[str, str] = {
    "runtime_backend": "backend",
    "surface_interaction_model": "surface_interaction_model",
    "partition_release_depth_m": "partition_release_depth_m",
    "runtime_max_iterations": "max_iterations",
    "runtime_tol_residual_inf": "tol_residual_inf",
    "runtime_tol_state_update_inf": "tol_state_update_inf",
    "vi_substeps_per_period": "vi_substeps_per_period",
    "vi_substep_on_failure": "vi_substep_on_failure",
    "vi_max_adaptive_substeps": "vi_max_adaptive_substeps",
    "ts_vi_steps_per_period": "ts_vi_steps_per_period",
    "ts_vi_adapt": "ts_vi_adapt",
    "ts_vi_dt_min_fraction": "ts_vi_dt_min_fraction",
    "ts_vi_dt_max_fraction": "ts_vi_dt_max_fraction",
    "ts_vi_type": "ts_vi_type",
    "ts_vi_snes_type": "ts_vi_snes_type",
}
"""What a key of [flow] was once called, mapped to its name in [solver.boussinesq].

These keys moved to ``[flow.runtime]`` first, and that table is ``[solver.boussinesq]``
since 2.1.0.
"""


__all__ = [
    "FlowBarrierConfig",
    "FlowBoundaryConditionConfig",
    "FlowConfig",
    "FlowLakeConfig",
    "FlowParam",
    "FlowSinksSourcesConfig",
    "FlowWellConfig",
    "RestartReference",
    "from_toml_section",
    "normalize_bc_payloads",
    "resolve_forcing_paths",
]


FlowConfigT = TypeVar("FlowConfigT", bound=BaseModel)

# Keys this loader parses itself before validation. Every other declared key is
# forwarded verbatim, so a new field on the flow model reaches it without any
# edit here.
_PREPARSED_KEYS = frozenset(
    {
        "param_list",
        "param",
        "param_values",
        "ic",
        "bc",
        "sinks_sources",
    }
)


def from_toml_section(
    flow_config_cls: type[FlowConfigT],
    flow_section: Mapping[str, object] | None,
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
) -> FlowConfigT:
    """Build a validated flow config from one `[flow]` TOML section.

    Keys listed in :data:`_PREPARSED_KEYS` are normalized here; every other
    declared key is forwarded as-is to the model, which applies its own
    defaults.
    """
    if flow_section is None:
        return flow_config_cls()
    if not isinstance(flow_section, Mapping):
        raise ValueError("TOML section 'flow' must be a mapping when provided")
    known_keys = set(flow_config_cls.model_fields) | {"param_values"}
    unknown_keys = sorted(set(flow_section) - known_keys)
    if unknown_keys:
        raise ValueError(f"Unknown TOML key(s) in [flow]: {', '.join(unknown_keys)}")

    raw_param_list = flow_section.get("param_list", [])
    if raw_param_list is None:
        raw_param_list = []
    if not isinstance(raw_param_list, (list, tuple)):
        raise ValueError("TOML section 'flow.param_list' must be a list of ids when provided")

    raw_param = flow_section.get("param", {})
    if raw_param is None:
        raw_param = {}
    if not isinstance(raw_param, Mapping):
        raise ValueError("TOML section 'flow.param' must be a mapping when provided")
    if flow_section.get("param_values") is not None:
        raise ValueError("TOML section 'flow.param_values' is no longer supported.")

    raw_bc = _mapping_section(flow_section, "bc")
    raw_ic = _mapping_section(flow_section, "ic")
    raw_sinks_sources = _mapping_section(flow_section, "sinks_sources")

    declared_param = list(raw_param_list)
    if len(declared_param) == 0 and len(raw_param) > 0:
        declared_param = list(raw_param.keys())

    parsed_sinks_sources = resolve_forcing_paths(
        raw_sinks_sources,
        base_dir=base_dir,
        workspace_data_dir=workspace_data_dir,
    )
    payload: dict[str, object] = {
        key: value for key, value in flow_section.items() if key not in _PREPARSED_KEYS
    }
    payload.update(
        {
            "param_list": declared_param,
            "param": raw_param,
            "ic": raw_ic,
            "bc": raw_bc,
            "sinks_sources": parsed_sinks_sources,
        }
    )
    return flow_config_cls.model_validate(
        payload,
        context={"base_dir": base_dir, "workspace_data_dir": workspace_data_dir},
    )


_FAMILY_KEYS = frozenset({"dirichlet", "cauchy", "robin"})


def normalize_bc_payloads(
    value: Mapping[str, object] | None,
    *,
    base_dir: Path | None = None,
    workspace_data_dir: Path | None = None,
) -> dict[str, object]:
    """Flatten `[flow.bc]` TOML sections into discriminated BC payloads."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("flow.bc must be a mapping payload")
    bc_cfg = (
        value
        if base_dir is None
        else resolve_forcing_paths(
            value,
            base_dir=base_dir,
            workspace_data_dir=workspace_data_dir,
            role="flow_bc",
        )
    )

    parsed: dict[str, object] = {}

    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in _FAMILY_KEYS:
            raise ValueError(
                f"[flow.bc.{key}.<id>] is no longer supported: a boundary is keyed by what it "
                "IS, not by the family it belongs to, which the registry already owns. Write "
                "[flow.bc.<id>]. " + prerelease_refusal("[flow.bc]", [key])
            )
        if raw_payload is None:
            continue
        if not isinstance(raw_payload, Mapping):
            raise TypeError(f"flow.bc.{key} must be a mapping payload")

        if key not in FLOW_BC_IDS:
            # A boundary is keyed by what it is, and only the ids of the table
            # exist; anything else there is a typo, not a new boundary.
            raise ValueError(
                f"flow.bc names the boundary '{key}', which [flow.bc] does not hold. It "
                f"holds {', '.join(FLOW_BC_IDS)}. A lake and a stream network are declared "
                "under [flow.sinks_sources]."
            )
        canonical_key = key
        default_kind = _default_kind_for(key)
        if canonical_key in parsed:
            raise ValueError(f"Duplicate boundary condition entry for '{canonical_key}' in flow.bc")
        parsed[canonical_key] = _prepare_bc_entry_payload(
            bc_id=canonical_key,
            raw_payload=raw_payload,
            default_kind=default_kind,
            location_prefix=f"flow.bc.{key}",
        )

    return parsed


def resolve_forcing_paths(
    section: Mapping[str, object],
    *,
    base_dir: Path,
    workspace_data_dir: Path | None = None,
    role: str | None = None,
) -> dict[str, object]:
    """Resolve the relative CSV paths of each entry of ``flow.bc`` or ``flow.sinks_sources``.

    A path resolves like every other ``InputFile`` field: against the TOML folder
    alone, with no search in ``<workspace>/data/``. ``role`` and
    ``workspace_data_dir`` no longer steer the path and are kept for the callers.
    """
    return {
        key: _resolve_csv_paths_in(
            item,
            base_dir=base_dir,
            role=role or str(key),
            workspace_data_dir=workspace_data_dir,
        )
        for key, item in section.items()
    }


def _resolve_csv_paths_in(
    node: object,
    *,
    base_dir: Path,
    role: str,
    workspace_data_dir: Path | None,
) -> object:
    """Return ``node`` with every nested CSV forcing ``path_file`` resolved."""
    if isinstance(node, Mapping):
        resolved: dict[str, object] = {}
        for key, value in node.items():
            resolved[str(key)] = _resolve_csv_paths_in(
                value,
                base_dir=base_dir,
                role=role,
                workspace_data_dir=workspace_data_dir,
            )
        if resolved.get("kind", "csv") == "csv" and isinstance(resolved.get("path_file"), str):
            return _resolve_forcing_path(
                resolved,
                base_dir=base_dir,
                role=role,
                workspace_data_dir=workspace_data_dir,
            )
        return resolved
    if isinstance(node, (list, tuple)):
        return [
            _resolve_csv_paths_in(
                item, base_dir=base_dir, role=role, workspace_data_dir=workspace_data_dir
            )
            for item in node
        ]
    return node


def _mapping_section(flow_section: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = flow_section.get(name, {})
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError(f"TOML section 'flow.{name}' must be a mapping when provided")
    return value


def _default_kind_for(bc_id: str) -> str:
    """Return the kind the registry declares for a boundary of ``[flow.bc]``."""
    return FLOW_BOUNDARY_DEFINITIONS[bc_id].default_type


def _prepare_bc_entry_payload(
    *,
    bc_id: str,
    raw_payload: Mapping[str, object],
    default_kind: str,
    location_prefix: str,
) -> dict[str, object]:
    """Normalize one bc payload, with the registry supplying the kind it omits.

    A boundary is keyed by what it IS. Its kind is an attribute the registry
    already declares, so writing it is never needed. Crossing families is refused:
    a head-dependent exchange is not a prescribed head, and a run that swapped
    them would solve another problem entirely.
    """
    payload = dict(raw_payload)
    raw_kind = str(payload.get("kind", default_kind)).strip().lower() or default_kind
    if raw_kind not in FLOW_BC_KINDS:
        raise ValueError(f"{location_prefix}.kind must be one of: {', '.join(FLOW_BC_KINDS)}")
    if (raw_kind == "dirichlet") != (default_kind == "dirichlet"):
        raise ValueError(
            f"{location_prefix}.kind is {raw_kind!r} but {bc_id!r} is a {default_kind!r} "
            "boundary in the registry. A prescribed head and a head-dependent exchange are "
            "not interchangeable."
        )
    payload["id"] = bc_id
    payload["kind"] = raw_kind
    payload["_location_prefix"] = location_prefix
    return payload


def _resolve_forcing_path(
    forcing: Mapping[str, Any],
    *,
    base_dir: Path,
    role: str,
    workspace_data_dir: Path | None = None,
) -> dict[str, object]:
    """Resolve one ``forcing.path_file`` against the project root / TOML directory."""
    forcing_payload = dict(forcing)
    path_value = forcing_payload.get("path_file")
    if isinstance(path_value, str) and path_value.strip() != "":
        forcing_payload["path_file"] = resolve_declared_path(
            path_value,
            base_dir=base_dir,
        )
    return forcing_payload


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
        **{old: f"it moved under [solver], as {new}." for old, new in FLOW_RUNTIME_KEYS.items()},
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
    bc: Annotated[dict[FlowBcId, BCEntry], Profile.USER] = Field(
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
            "package. The Boussinesq solver takes its surface closure from the "
            "surface-interaction settings under [solver]."
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

    @property
    def active_bc(self) -> list[str]:
        """Return the boundaries this run builds: those declared and not switched off.

        'lake' and 'sfr' stand for the tables of ``sinks_sources`` that build a lake and a
        stream network, so only a solver that lists them in its ``supports`` takes them.
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
        says so. A solver that leaves it out of its ``supports`` refuses it when the file is read.
        """
        tables = self.sinks_sources
        active: list[str] = []
        if tables.recharge is not None and tables.recharge.enabled:
            active.append(RECHARGE)
        if tables.enabled_wells():
            active.append(WELLS)
        if tables.etp is not None and tables.etp.enabled:
            active.append(ETP)
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
        return normalize_bc_payloads(
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
        return from_toml_section(
            cls,
            flow_section,
            base_dir=base_dir,
            workspace_data_dir=workspace_data_dir,
        )
