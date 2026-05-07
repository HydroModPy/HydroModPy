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
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr
from hydromodpy.physics.base import ProcessSpatialConfig
from hydromodpy.physics.flow import flow_toml_loader
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
    FieldParamConfig,
    FieldSection,
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
        examples=["steady", "transient"],
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
            examples=["local", "scipy_sparse"],
            json_schema_extra={"stability": "experimental"},
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
        examples=["auto", "regularized_partition"],
        json_schema_extra={"stability": "experimental"},
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
            "**Default units:** ``m`` for dirichlet, ``m2/s`` for cauchy/robin.\n"
            "\n"
            "**Cauchy vs Robin:** both map to the same MODFLOW ``DRN`` package; "
            "the distinction only matters for the Boussinesq solver, which uses "
            "two different surface-interaction closures (``cauchy`` for the "
            "linear formulation ``q = C(h - h_ref)``, ``robin`` for the "
            "regularized partition / complementarity variants selected by "
            "``flow.surface_interaction_model``)."
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
    active_sinks_sources: Annotated[list[IdentifierStr], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicitly activated sink/source names for this flow run. "
            "Allowed values: 'recharge', 'wells'. "
            "An empty list means no sink/source package is assembled by the solver."
        ),
        examples=[["recharge"], ["recharge", "wells"]],
    )
    active_bc: Annotated[list[IdentifierStr], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicitly activated boundary-condition ids for this flow run. "
            "Allowed values: 'ocean', 'stream', 'north_side', 'south_side', "
            "'east_side', 'west_side', 'drainage'. "
            "An empty list means no boundary-condition package is assembled by the solver."
        ),
        examples=[["ocean"], ["west_side", "east_side", "drainage"]],
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
        return flow_toml_loader.normalize_bc_payloads(value, base_dir=base_dir)

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
            "field": {"id": param_id, "kind": "homogeneous", "unit": unit, "value": float(value)}
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
        """Build a validated `FlowConfig` from the `[flow]` TOML section."""
        return flow_toml_loader.from_toml_section(cls, flow_section, base_dir=base_dir)
