"""Pydantic configuration model for flow-process definitions.

This module validates and normalizes `[flow]`, `[flow.param.<id>]`, `[flow.ic]`,
`[flow.bc]`, and `[flow.sinks_sources]` payloads from TOML into objects
consumable by `Flow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.base import ProcessSpatialConfig
from hydromodpy.physics.flow.boundary_conditions import (
    DIRICHLET_BC_CANONICAL_DOMAINS,
    BCEntry,
    FlowBoundaryConditionConfig,
)
from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialConditions,
)
from hydromodpy.physics.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)
from hydromodpy.physics.flow.regime import FlowRegime, normalize_flow_regime
from hydromodpy.physics.flow.sinks_sources import (
    FlowSinksSourcesConfig,
    FlowWellConfig,
)
from hydromodpy.physics.flow.sinks_sources_config import (
    normalize_flow_sinks_sources,
)
from hydromodpy.spatial.field.core.field_param_config import (
    FieldBaseSection,
    FieldHeterogeneousSection,
    FieldHomogeneousSection,
    FieldParamConfig,
    FieldVerticalProfileSection,
    resolve_field_param_config_payload,
)

__all__ = [
    "FlowBoundaryConditionConfig",
    "FlowParam",
    "FlowWellConfig",
    "FlowSinksSourcesConfig",
    "FlowRuntimeConfig",
    "FlowConfig",
]


class FlowRuntimeConfig(HydroModelBase):
    """Grouped view of the Boussinesq runtime fields on :class:`FlowConfig`.

    The spec (``02_config_pydantic.md`` §3.3) groups all runtime-only
    Boussinesq solver knobs under a single ``runtime`` sub-block so that
    user-facing templates do not scatter ``runtime_backend``,
    ``runtime_max_iterations`` and ``runtime_tol_*`` at the top of
    ``[flow]``. We keep the flat flow-config fields for existing
    consumers and expose this dataclass-style view via
    :attr:`FlowConfig.runtime` for new call-sites.
    """

    backend: Annotated[Literal["local", "scipy", "scipy_sparse", "petsc"], Profile.DEV] = Field(
        default="local",
        description=("Nonlinear runtime backend used by Boussinesq-style solvers."),
    )
    surface_model: Annotated[
        Literal["auto", "regularized_partition", "complementarity"], Profile.DEV
    ] = Field(
        default="auto",
        description=(
            "Surface-interaction closure selector (Boussinesq). "
            "``regularized_partition`` uses the Marcais-style q_ex = G_r(theta) "
            "R(balance) law; ``complementarity`` uses the PETSc "
            "q_ex-perp-(z_top-h) formulation; ``auto`` keeps the historical "
            "backend-dependent default."
        ),
    )
    max_iterations: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Optional override for the nonlinear iteration budget.",
    )
    tol_residual_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Optional override for the inf-norm residual tolerance.",
    )
    tol_state_update_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="Optional override for the inf-norm state-update tolerance.",
    )


class FlowParam(FieldParamConfig):
    """Flow parameter payload using native field-param sections."""

    model_config = ConfigDict(extra="forbid")

    field: Annotated[FieldBaseSection, Profile.USER] = Field(
        ...,
        description="Base section `[field]` with parameter id and kind.",
    )
    field_homogeneous: Annotated[FieldHomogeneousSection | None, Profile.USER] = Field(
        default=None,
        description="Homogeneous parameters section `[field_homogeneous]`.",
    )
    field_heterogeneous: Annotated[FieldHeterogeneousSection | None, Profile.USER] = Field(
        default=None,
        description="Heterogeneous parameters section `[field_heterogeneous]`.",
    )
    field_vertical_profile: Annotated[FieldVerticalProfileSection | None, Profile.USER] = Field(
        default=None,
        description="Optional depth profile section `[field_vertical_profile]`.",
    )

    _base_dir: Path | None = PrivateAttr(default=None)
    _section_label: str = PrivateAttr(default="flow.param")

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_payload(cls, data):
        if isinstance(data, FlowParam):
            return data
        if not isinstance(data, Mapping):
            raise ValueError("flow.param.<id> must be a mapping payload")

        payload = dict(data)
        raw_param_id = payload.pop("_param_id", None)
        param_id = str(raw_param_id).strip() if raw_param_id is not None else None
        section_label = str(payload.pop("_section_label", "flow.param"))

        if "field_common" in payload:
            raise ValueError(
                "`[field_common]` is no longer supported. Move shared keys to `[field]`."
            )

        if cls._has_field_sections(payload):
            canonical = cls._canonicalize_sectioned_payload(
                payload,
                param_id=param_id,
                section_label=section_label,
            )
        else:
            canonical = cls._canonicalize_compact_payload(
                payload,
                param_id=param_id,
                section_label=section_label,
            )
        return canonical

    def model_post_init(self, context: Any) -> None:
        super().model_post_init(context)
        if isinstance(context, Mapping):
            raw_base_dir = context.get("base_dir")
            if isinstance(raw_base_dir, Path):
                self._base_dir = raw_base_dir
        self._section_label = self._section_label_from_field()

    @classmethod
    def _has_field_sections(cls, payload: Mapping[str, object]) -> bool:
        return any(
            key in payload
            for key in (
                "field",
                "field_homogeneous",
                "field_heterogeneous",
                "field_vertical_profile",
            )
        )

    @classmethod
    def _canonicalize_sectioned_payload(
        cls,
        payload: Mapping[str, object],
        *,
        param_id: str | None,
        section_label: str,
    ) -> dict[str, object]:
        field_payload = payload.get("field")
        if not isinstance(field_payload, Mapping):
            raise KeyError(f"{section_label} requires section [{section_label}.field]")
        field = dict(field_payload)
        cls._apply_param_id(field, param_id=param_id, section_label=section_label)

        canonical: dict[str, object] = {"field": field}
        for key in ("field_homogeneous", "field_heterogeneous", "field_vertical_profile"):
            value = payload.get(key)
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise ValueError(f"{section_label}.{key} must be a mapping")
            canonical[key] = dict(value)
        return canonical

    @classmethod
    def _canonicalize_compact_payload(
        cls,
        payload: Mapping[str, object],
        *,
        param_id: str | None,
        section_label: str,
    ) -> dict[str, object]:
        field: dict[str, object] = {}
        for key in ("id", "kind", "unit"):
            if key in payload:
                field[key] = payload[key]
        cls._apply_param_id(field, param_id=param_id, section_label=section_label)

        kind = str(field.get("kind", "")).strip().lower()
        if kind == "":
            raise KeyError(f"{section_label}.field.kind is required")

        canonical: dict[str, object] = {"field": field}
        if kind == "homogeneous":
            if "value" not in payload:
                raise KeyError(f"{section_label}.field_homogeneous.value is required")
            canonical["field_homogeneous"] = {"value": payload["value"]}
        elif kind == "heterogeneous":
            heterogeneous: dict[str, object] = {}
            for key in (
                "values_source",
                "values",
                "values_csv_file",
                "csv_key_column",
                "csv_value_column",
                "field_spatial_id",
            ):
                if key in payload:
                    heterogeneous[key] = payload[key]
            canonical["field_heterogeneous"] = heterogeneous
        else:
            raise ValueError(f"{section_label}.field.kind must be 'homogeneous' or 'heterogeneous'")

        vertical_profile = payload.get("vertical_profile", payload.get("field_vertical_profile"))
        if vertical_profile is not None:
            if not isinstance(vertical_profile, Mapping):
                raise ValueError(f"{section_label}.field_vertical_profile must be a mapping")
            canonical["field_vertical_profile"] = dict(vertical_profile)
        return canonical

    @classmethod
    def _apply_param_id(
        cls,
        field: dict[str, object],
        *,
        param_id: str | None,
        section_label: str,
    ) -> None:
        field_id = str(field.get("id", "")).strip()
        if param_id is None or param_id == "":
            if field_id == "":
                raise KeyError(f"{section_label}.field.id is required")
            return
        if field_id == "":
            field["id"] = param_id
            return
        if field_id != param_id:
            raise ValueError(
                f"{section_label}.field.id must match section key '{param_id}', got '{field_id}'"
            )

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


class FlowConfig(ProcessSpatialConfig):
    """Flow-process configuration.

    Parameters are declared in `param_list` (ordered list of ids), and
    parameter payloads are stored in `param`.
    """

    flow_regime: Annotated[FlowRegime, Profile.USER] = Field(
        default="transient",
        description=(
            "Global flow simulation regime used by solvers consuming [flow] (steady or transient)."
        ),
        json_schema_extra={
            "widget_type": "select",
            "unit": "-",
            "display_name_fr": "Régime d'écoulement",
            "help_text_fr": (
                "Régime stationnaire (steady) ou transitoire (transient). "
                "Le régime transitoire requiert une condition initiale [flow.ic]."
            ),
        },
    )
    runtime_backend: Annotated[Literal["local", "scipy", "scipy_sparse", "petsc"], Profile.DEV] = (
        Field(
            default="local",
            description=(
                "Optional nonlinear runtime backend hint used by the Boussinesq "
                "solver implementation. Other flow solvers may ignore this field."
            ),
        )
    )
    surface_interaction_model: Annotated[
        Literal["auto", "regularized_partition", "complementarity"],
        Profile.DEV,
    ] = Field(
        default="auto",
        description=(
            "Optional Boussinesq surface-interaction closure selector. "
            "'regularized_partition' uses the Marcais-style q_ex = G_r(theta) "
            "R(balance) law; 'complementarity' uses the mixed PETSc "
            "q_ex-perp-(z_top-h) formulation; 'auto' keeps the historical "
            "backend-dependent default."
        ),
    )
    runtime_max_iterations: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the nonlinear iteration budget used by the "
            "Boussinesq runtime backend."
        ),
        json_schema_extra={
            "widget_type": "input",
            "unit": "-",
            "display_name_fr": "Itérations max (solveur)",
            "help_text_fr": "Budget d'itérations non-linéaires pour le solveur.",
            "display_min": 1,
            "display_max": 100_000,
        },
    )
    runtime_tol_residual_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the infinity-norm residual tolerance used "
            "by the Boussinesq runtime backend."
        ),
    )
    runtime_tol_state_update_inf: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional override for the infinity-norm state-update tolerance "
            "used by Boussinesq backends that track it."
        ),
    )
    param_list: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered list of flow-parameter identifiers used to build runtime "
            "parameters (for example ['K', 'Ss', 'Sy'])."
        ),
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
            "- ``[flow.bc.dirichlet.<id>]`` where ``<id>`` is one of "
            "``ocean``, ``stream``, ``north_side``, ``south_side``, "
            "``east_side``, ``west_side``\n"
            "- ``[flow.bc.cauchy.drainage]``\n"
            "- ``[flow.bc.robin.drainage]``\n"
            "- ``[flow.bc.<custom_id>]`` for generic payloads\n"
            "\n"
            "**Common keys**\n"
            "\n"
            "- ``value`` (required): numeric or ``'<value> <unit>'``\n"
            "- ``application_domain``: optional for dirichlet when ``<id>`` "
            "implies it (e.g. ``west_side`` -> ``'west side'``); required "
            "for ``cauchy`` and ``robin`` drainage\n"
            "\n"
            "**Allowed application_domain values:** ``top``, ``north side``, "
            "``south side``, ``east side``, ``west side``.\n"
            "\n"
            "**Default units:** ``m`` for dirichlet, ``m2/s`` for cauchy/robin."
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
    active_sinks_sources: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicitly activated sink/source names for this flow run. "
            "Allowed values: 'recharge', 'wells'. "
            "An empty list means no sink/source package is assembled by the solver."
        ),
    )
    active_bc: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicitly activated boundary-condition ids for this flow run. "
            "Allowed values: 'ocean', 'stream', 'north_side', 'south_side', "
            "'east_side', 'west_side', 'drainage'. "
            "An empty list means no boundary-condition package is assembled by the solver."
        ),
    )

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
            if isinstance(raw_payload, FlowParam):
                out[param_id] = raw_payload
                continue
            if not isinstance(raw_payload, Mapping):
                raise ValueError(f"flow.param['{param_id}'] must be a mapping payload")
            payload = dict(raw_payload)
            payload["_param_id"] = param_id
            payload["_section_label"] = f"flow.param.{param_id}"
            out[param_id] = payload
        return out

    @model_validator(mode="after")
    def _validate_param_consistency(self):
        """Enforce one-to-one consistency between `param_list` and `param` keys."""
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
        return self

    @field_validator("flow_regime", mode="before")
    @classmethod
    def _validate_flow_regime(cls, value):
        """Validate flow regime enumeration."""
        return normalize_flow_regime(value)

    @field_validator("runtime_backend", mode="before")
    @classmethod
    def _validate_runtime_backend(cls, value):
        """Normalize the optional Boussinesq runtime backend selector."""
        text = str(value or "local").strip().lower()
        if text not in {"local", "scipy", "scipy_sparse", "petsc"}:
            raise ValueError(
                "flow.runtime_backend must be 'local', 'scipy', 'scipy_sparse', or 'petsc'"
            )
        return text

    @field_validator("surface_interaction_model", mode="before")
    @classmethod
    def _validate_surface_interaction_model(cls, value):
        """Normalize the optional Boussinesq surface-interaction selector."""
        text = str(value or "auto").strip().lower() or "auto"
        if text not in {"auto", "regularized_partition", "complementarity"}:
            raise ValueError(
                "flow.surface_interaction_model must be 'auto', "
                "'regularized_partition', or 'complementarity'"
            )
        return text

    @field_validator("runtime_max_iterations", mode="before")
    @classmethod
    def _validate_runtime_max_iterations(cls, value):
        """Validate one optional nonlinear iteration-budget override."""
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("flow.runtime_max_iterations must be a positive integer")
        numeric = float(value)
        if not numeric.is_integer() or numeric <= 0:
            raise ValueError("flow.runtime_max_iterations must be a positive integer")
        return int(numeric)

    @field_validator("runtime_tol_residual_inf", "runtime_tol_state_update_inf", mode="before")
    @classmethod
    def _validate_runtime_tolerances(cls, value, info):
        """Validate optional positive runtime tolerances."""
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"flow.{info.field_name} must be a positive number")
        numeric = float(value)
        if numeric <= 0.0:
            raise ValueError(f"flow.{info.field_name} must be a positive number")
        return numeric

    @field_validator("bc", mode="before")
    @classmethod
    def _validate_bc(cls, value, info: ValidationInfo):
        """Normalize boundary-condition payloads from `[flow.bc]`."""
        context = info.context if isinstance(info.context, Mapping) else {}
        raw_base_dir = context.get("base_dir")
        base_dir = raw_base_dir if isinstance(raw_base_dir, Path) else None
        return cls._normalize_bc_payloads(value, base_dir=base_dir)

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
        return normalize_flow_sinks_sources(value, location_prefix="flow.sinks_sources")

    @field_validator("active_sinks_sources", mode="before")
    @classmethod
    def _validate_active_sinks_sources(cls, value):
        """
        Validate that ``active_sinks_sources`` only contains allowed values.

        For ``Flow``, the permitted sink/source identifiers are
        ``'recharge'``, ``'wells'`` and ``'etp'``. Any other value is an
        error. Duplicates are rejected to keep the list unambiguous.
        """
        _ALLOWED = {"recharge", "wells", "etp"}
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("flow.active_sinks_sources must be a list")
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = str(raw).strip()
            if name not in _ALLOWED:
                allowed_text = ", ".join(sorted(_ALLOWED))
                raise ValueError(
                    f"flow.active_sinks_sources: '{name}' is not a valid sink/source "
                    f"for Flow. Allowed values: {allowed_text}."
                )
            if name in seen:
                raise ValueError(f"flow.active_sinks_sources cannot contain duplicates: '{name}'")
            seen.add(name)
            out.append(name)
        return out

    @field_validator("active_bc", mode="before")
    @classmethod
    def _validate_active_bc(cls, value):
        """
        Validate that ``active_bc`` only contains allowed boundary-condition ids.

        For ``Flow``, permitted ids are those declared in
        ``DIRICHLET_BC_CANONICAL_DOMAINS`` (ocean, stream, north_side,
        south_side, east_side, west_side) plus ``'drainage'``.
        Duplicates are rejected to keep the list unambiguous.
        """
        _ALLOWED = set(DIRICHLET_BC_CANONICAL_DOMAINS.keys()) | {"drainage"}
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("flow.active_bc must be a list")
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = str(raw).strip()
            if name not in _ALLOWED:
                allowed_text = ", ".join(sorted(_ALLOWED))
                raise ValueError(
                    f"flow.active_bc: '{name}' is not a valid boundary-condition id "
                    f"for Flow. Allowed values: {allowed_text}."
                )
            if name in seen:
                raise ValueError(f"flow.active_bc cannot contain duplicates: '{name}'")
            seen.add(name)
            out.append(name)
        return out

    @property
    def runtime(self) -> FlowRuntimeConfig:
        """Return the grouped Boussinesq runtime view.

        Architecture spec ``02_config_pydantic.md`` §3.3 groups
        Boussinesq runtime knobs under a single sub-block. The flat
        ``runtime_*`` fields on :class:`FlowConfig` remain the source of
        truth; this property exposes a structured view assembled on
        demand for consumers that prefer one object over scattered
        attributes.
        """
        return FlowRuntimeConfig(
            backend=self.runtime_backend,
            surface_model=self.surface_interaction_model,
            max_iterations=self.runtime_max_iterations,
            tol_residual_inf=self.runtime_tol_residual_inf,
            tol_state_update_inf=self.runtime_tol_state_update_inf,
        )

    _DEFAULT_PARAM_UNITS: ClassVar[dict[str, str]] = {
        "K": "m/s",
        "Kx": "m/s",
        "Ky": "m/s",
        "Kz": "m/s",
        "Ss": "1/m",
        "Sy": "-",
        "porosity": "-",
        "n": "-",
    }

    @classmethod
    def _homogeneous_param_entry(cls, param_id: str, value: float) -> dict:
        unit = cls._DEFAULT_PARAM_UNITS.get(param_id, "-")
        return {
            "field": {"id": param_id, "kind": "homogeneous", "unit": unit},
            "field_homogeneous": {"value": float(value)},
        }

    @classmethod
    def homogeneous(
        cls,
        *,
        flow_regime: FlowRegime = "transient",
        active_bc: list[str] | None = None,
        active_sinks_sources: list[str] | None = None,
        **parameters: float,
    ) -> FlowConfig:
        """Build a FlowConfig with homogeneous parameters.

        Pass K, Sy, Ss, porosity etc. as keyword arguments. Each becomes a
        homogeneous scalar parameter. Units are inferred from the canonical
        names (K in m/s, Ss in 1/m, Sy dimensionless).
        """
        if not parameters:
            raise ValueError("homogeneous() requires at least one parameter (e.g. K=5e-5)")
        return cls(
            flow_regime=flow_regime,
            param_list=list(parameters),
            param={pid: cls._homogeneous_param_entry(pid, v) for pid, v in parameters.items()},
            active_bc=active_bc or [],
            active_sinks_sources=active_sinks_sources or [],
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
    ) -> FlowConfig:
        """
        Build a validated `FlowConfig` from the `[flow]` TOML section.

        Processing steps:
        1. Validate raw section shapes.
        2. Parse and resolve parameter sections (`flow.param.<id>`).
        3. Normalize IC/BC/sinks-sources sections.
        4. Validate the final typed model with Pydantic.
        """
        if flow_section is None:
            return cls()
        if not isinstance(flow_section, Mapping):
            raise ValueError("TOML section 'flow' must be a mapping when provided")
        known_keys = set(cls.model_fields) | {"param_values"}
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

        raw_bc = flow_section.get("bc", {})
        if raw_bc is None:
            raw_bc = {}
        if not isinstance(raw_bc, Mapping):
            raise ValueError("TOML section 'flow.bc' must be a mapping when provided")

        raw_ic = flow_section.get("ic", {})
        if raw_ic is None:
            raw_ic = {}
        if not isinstance(raw_ic, Mapping):
            raise ValueError("TOML section 'flow.ic' must be a mapping when provided")

        raw_sinks_sources = flow_section.get("sinks_sources", {})
        if raw_sinks_sources is None:
            raw_sinks_sources = {}
        if not isinstance(raw_sinks_sources, Mapping):
            raise ValueError("TOML section 'flow.sinks_sources' must be a mapping when provided")

        raw_active_sinks_sources = flow_section.get("active_sinks_sources", [])
        if raw_active_sinks_sources is None:
            raw_active_sinks_sources = []
        if not isinstance(raw_active_sinks_sources, (list, tuple)):
            raise ValueError(
                "TOML section 'flow.active_sinks_sources' must be a list when provided"
            )

        raw_active_bc = flow_section.get("active_bc", [])
        if raw_active_bc is None:
            raw_active_bc = []
        if not isinstance(raw_active_bc, (list, tuple)):
            raise ValueError("TOML section 'flow.active_bc' must be a list when provided")

        parsed_param = raw_param
        declared_param = list(raw_param_list)
        if len(declared_param) == 0 and len(parsed_param) > 0:
            declared_param = list(parsed_param.keys())

        # Keep raw TOML payloads for IC/BC/sinks_sources here and let field
        # validators normalize exactly once.
        #
        # Rationale:
        # - `FlowConfig` already defines dedicated validators for `ic`, `bc`,
        #   and `sinks_sources`;
        # - pre-normalizing here and validating again may trigger false legacy
        #   detections (for example normalized key "drainage" seen as deprecated
        #   input on second pass).
        parsed_ic = raw_ic
        parsed_bc = raw_bc
        parsed_sinks_sources = _resolve_well_forcing_paths(
            raw_sinks_sources,
            base_dir=base_dir,
        )
        raw_flow_regime = flow_section.get("flow_regime", "transient")
        raw_runtime_backend = flow_section.get("runtime_backend", "local")
        raw_surface_interaction_model = flow_section.get(
            "surface_interaction_model",
            "auto",
        )
        raw_runtime_max_iterations = flow_section.get("runtime_max_iterations")
        raw_runtime_tol_residual_inf = flow_section.get("runtime_tol_residual_inf")
        raw_runtime_tol_state_update_inf = flow_section.get("runtime_tol_state_update_inf")
        return cls.model_validate(
            {
                "flow_regime": raw_flow_regime,
                "runtime_backend": raw_runtime_backend,
                "surface_interaction_model": raw_surface_interaction_model,
                "runtime_max_iterations": raw_runtime_max_iterations,
                "runtime_tol_residual_inf": raw_runtime_tol_residual_inf,
                "runtime_tol_state_update_inf": raw_runtime_tol_state_update_inf,
                "param_list": declared_param,
                "param": parsed_param,
                "ic": parsed_ic,
                "bc": parsed_bc,
                "sinks_sources": parsed_sinks_sources,
                "active_sinks_sources": list(raw_active_sinks_sources),
                "active_bc": list(raw_active_bc),
            },
            context={"base_dir": base_dir},
        )

    @classmethod
    def _normalize_bc_payloads(
        cls,
        value: Mapping[str, object] | None,
        *,
        base_dir: Path | None = None,
    ) -> dict[str, object]:
        """Flatten `[flow.bc]` TOML sections into discriminated BC payloads."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.bc must be a mapping payload")
        bc_cfg: Mapping[str, object]
        if base_dir is None:
            bc_cfg = value
        else:
            bc_cfg = cls._resolve_bc_forcing_paths(value, base_dir=base_dir)

        parsed: dict[str, object] = {}

        dirichlet_payload = bc_cfg.get("dirichlet")
        if dirichlet_payload is not None:
            if not isinstance(dirichlet_payload, Mapping):
                raise ValueError("flow.bc.dirichlet must be a mapping when provided")
            for raw_key, item in dirichlet_payload.items():
                key = str(raw_key).strip()
                if key == "":
                    raise ValueError("flow.bc.dirichlet cannot contain empty keys")
                if item is None:
                    continue
                if not isinstance(item, Mapping):
                    raise ValueError(f"flow.bc.dirichlet.{key} must be a mapping")
                canonical_key = cls._canonicalize_dirichlet_bc_id(
                    raw_bc_id=key,
                    location_prefix=f"flow.bc.dirichlet.{key}",
                )
                if canonical_key in parsed:
                    raise ValueError(
                        f"Duplicate Dirichlet entry for '{canonical_key}' in flow.bc.dirichlet"
                    )
                parsed[canonical_key] = cls._prepare_bc_entry_payload(
                    bc_id=canonical_key,
                    raw_payload=item,
                    default_type="dirichlet",
                    location_prefix=f"flow.bc.dirichlet.{key}",
                    force_dirichlet=True,
                )

        cauchy_payload = bc_cfg.get("cauchy")
        if cauchy_payload is not None:
            if not isinstance(cauchy_payload, Mapping):
                raise ValueError("flow.bc.cauchy must be a mapping when provided")
            drainage_item = cauchy_payload.get("drainage")
            if drainage_item is not None:
                if not isinstance(drainage_item, Mapping):
                    raise ValueError("flow.bc.cauchy.drainage must be a mapping")
                parsed["drainage"] = cls._prepare_bc_entry_payload(
                    bc_id="drainage",
                    raw_payload=drainage_item,
                    default_type="cauchy",
                    location_prefix="flow.bc.cauchy.drainage",
                )

        robin_payload = bc_cfg.get("robin")
        if robin_payload is not None and "drainage" not in parsed:
            if not isinstance(robin_payload, Mapping):
                raise ValueError("flow.bc.robin must be a mapping when provided")
            drainage_item = robin_payload.get("drainage")
            if drainage_item is not None:
                if not isinstance(drainage_item, Mapping):
                    raise ValueError("flow.bc.robin.drainage must be a mapping")
                parsed["drainage"] = cls._prepare_bc_entry_payload(
                    bc_id="drainage",
                    raw_payload=drainage_item,
                    default_type="robin",
                    location_prefix="flow.bc.robin.drainage",
                )

        for raw_key, raw_payload in bc_cfg.items():
            key = str(raw_key).strip()
            if key == "":
                raise ValueError("flow.bc cannot contain empty keys")
            if key in {"dirichlet", "cauchy", "robin"}:
                continue
            if key == "drainage":
                if (
                    isinstance(raw_payload, Mapping)
                    and str(raw_payload.get("id", "")).strip() == "drainage"
                    and str(raw_payload.get("type", "")).strip().lower() in {"cauchy", "robin"}
                ):
                    parsed[key] = cls._prepare_bc_entry_payload(
                        bc_id=key,
                        raw_payload=raw_payload,
                        default_type=str(raw_payload.get("type")).strip().lower(),
                        location_prefix=f"flow.bc.{key}",
                    )
                    continue
                raise ValueError(
                    "flow.bc.drainage is no longer supported. "
                    "Use flow.bc.cauchy.drainage or flow.bc.robin.drainage."
                )
            if not isinstance(raw_payload, Mapping):
                raise TypeError(f"flow.bc.{key} must be a mapping payload")

            if key in DIRICHLET_BC_CANONICAL_DOMAINS:
                if key in parsed:
                    raise ValueError(f"Duplicate boundary condition entry for '{key}' in flow.bc")
                parsed[key] = cls._prepare_bc_entry_payload(
                    bc_id=key,
                    raw_payload=raw_payload,
                    default_type="dirichlet",
                    location_prefix=f"flow.bc.{key}",
                    force_dirichlet=True,
                )
            else:
                parsed[key] = cls._prepare_bc_entry_payload(
                    bc_id=key,
                    raw_payload=raw_payload,
                    default_type="dirichlet",
                    location_prefix=f"flow.bc.{key}",
                )

        return parsed

    @classmethod
    def _prepare_bc_entry_payload(
        cls,
        *,
        bc_id: str,
        raw_payload: Mapping[str, object],
        default_type: str,
        location_prefix: str,
        force_dirichlet: bool = False,
    ) -> dict[str, object]:
        payload = dict(raw_payload)
        raw_type = str(payload.get("type", default_type)).strip().lower() or default_type
        if force_dirichlet and raw_type != "dirichlet":
            raise ValueError(f"{location_prefix}.type must be 'dirichlet'")
        if raw_type not in {"dirichlet", "cauchy", "robin"}:
            raise ValueError(f"{location_prefix}.type must be one of: dirichlet, cauchy, robin")
        payload["id"] = bc_id
        payload["type"] = raw_type
        payload["_location_prefix"] = location_prefix
        return payload

    @classmethod
    def _canonicalize_dirichlet_bc_id(
        cls,
        *,
        raw_bc_id: str,
        location_prefix: str,
    ) -> str:
        bc_id = str(raw_bc_id).strip()
        if bc_id == "":
            raise ValueError(f"{location_prefix} cannot be empty")
        if bc_id in DIRICHLET_BC_CANONICAL_DOMAINS:
            return bc_id
        supported_text = ", ".join(sorted(DIRICHLET_BC_CANONICAL_DOMAINS))
        raise ValueError(
            f"{location_prefix} contains unsupported Dirichlet key '{bc_id}'. "
            f"Supported keys: {supported_text}"
        )

    @classmethod
    def _resolve_bc_forcing_paths(
        cls,
        raw_bc: Mapping[str, object],
        *,
        base_dir: Path,
    ) -> dict[str, object]:
        """Resolve relative CSV paths declared under flow.bc.*.forcing."""
        payload = dict(raw_bc)

        def resolve_forcing_mapping(item: object) -> object:
            if not isinstance(item, Mapping):
                return item
            item_payload = dict(item)
            forcing = item_payload.get("forcing")
            if isinstance(forcing, Mapping):
                forcing_payload = dict(forcing)
                path_value = forcing_payload.get("path_file")
                if isinstance(path_value, str) and path_value.strip() != "":
                    path = Path(path_value).expanduser()
                    if not path.is_absolute():
                        path = (base_dir / path).resolve()
                    forcing_payload["path_file"] = path
                item_payload["forcing"] = forcing_payload
            return item_payload

        for section_key in ("dirichlet", "cauchy", "robin"):
            section = payload.get(section_key)
            if not isinstance(section, Mapping):
                continue
            resolved_section: dict[str, object] = {}
            for bc_id, raw_item in section.items():
                resolved_section[str(bc_id)] = resolve_forcing_mapping(raw_item)
            payload[section_key] = resolved_section

        for key, raw_item in list(payload.items()):
            if key in {"dirichlet", "cauchy", "robin"}:
                continue
            payload[key] = resolve_forcing_mapping(raw_item)

        return payload


def _parse_flow_ic_section(ic_cfg: Mapping[str, object]) -> FlowInitialConditions | None:
    """
    Parse and normalize one single `[flow.ic]` payload.

    Supported shapes:
    - Preferred: flat `[flow.ic]` with keys `type`, `value`, `unit|units`, `description`,
      where `value` can be numeric or `"<value> <unit>"`.
    """
    return normalize_flow_initial_conditions(ic_cfg, location_prefix="flow.ic")


def _resolve_well_forcing_paths(
    raw_sinks_sources: Mapping[str, object],
    *,
    base_dir: Path,
) -> dict[str, object]:
    """Resolve relative CSV paths declared under flow.sinks_sources.wells.*.forcing."""
    payload = dict(raw_sinks_sources)
    wells = payload.get("wells")
    if not isinstance(wells, Mapping):
        return payload

    resolved_wells: dict[str, object] = {}
    for well_id, raw_well in wells.items():
        if not isinstance(raw_well, Mapping):
            resolved_wells[str(well_id)] = raw_well
            continue
        well_payload = dict(raw_well)
        forcing = well_payload.get("forcing")
        if isinstance(forcing, Mapping):
            forcing_payload = dict(forcing)
            path_value = forcing_payload.get("path_file")
            if isinstance(path_value, str) and path_value.strip() != "":
                path = Path(path_value).expanduser()
                if not path.is_absolute():
                    path = (base_dir / path).resolve()
                forcing_payload["path_file"] = path
            well_payload["forcing"] = forcing_payload
        resolved_wells[str(well_id)] = well_payload
    payload["wells"] = resolved_wells
    return payload
