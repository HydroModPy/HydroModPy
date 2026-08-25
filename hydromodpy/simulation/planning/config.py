"""Declarative simulation configuration models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    CoveragePolicy,
    IdentifierStr,
    TimePeriodUnit,
)
from hydromodpy.core.contracts.solver_registry import get_solver_registry_provider
from hydromodpy.core.units import normalize_time_unit, parse_scalar_and_unit
from hydromodpy.simulation.planning.results_config import ResultsConfig

_VALID_STEP_UNITS = {"hour", "day", "month", "year"}
_STEP_UNIT_ALIASES = {
    "m": "month",
    "mo": "month",
    "mon": "month",
    "month": "month",
    "months": "month",
    "hours": "hour",
    "days": "day",
    "years": "year",
}


def _coerce_step_unit(token: str) -> TimePeriodUnit:
    """Resolve one user-facing step-unit token to the canonical literal."""
    cleaned = token.strip().lower()
    if cleaned == "":
        raise ValueError("simulation.time.step_unit cannot be empty.")
    if cleaned in _STEP_UNIT_ALIASES:
        return _STEP_UNIT_ALIASES[cleaned]  # type: ignore[return-value]
    try:
        canonical = normalize_time_unit(cleaned)
    except ValueError as exc:
        raise ValueError(
            "simulation.time.step_unit must be one of: hour, day, month, year."
        ) from exc
    resolved = _STEP_UNIT_ALIASES.get(canonical, canonical)
    if resolved not in _VALID_STEP_UNITS:
        raise ValueError("simulation.time.step_unit must be one of: hour, day, month, year.")
    return resolved  # type: ignore[return-value]


class SimulationTimeConfig(HydroModelBase):
    """Canonical simulation time window and forcing-coverage policy."""

    start_datetime: Annotated[datetime | None, Profile.USER] = Field(
        default=None,
        description=(
            "Simulation window lower datetime bound used by launcher-level "
            "time alignment and forcing checks."
        ),
        examples=["2019-01-01"],
    )
    end_datetime: Annotated[datetime | None, Profile.USER] = Field(
        default=None,
        description=(
            "Simulation window upper datetime bound, interpreted as inclusive. "
            "Must be greater than or equal to start_datetime."
        ),
        examples=["2025-12-31"],
    )
    step_value: Annotated[int | float | str, Profile.USER] = Field(
        default="1 month",
        description=(
            "Forcing/stress-period time-step scalar or inline token '<value> <unit>' "
            "(for example '30 day'). "
            "This controls the temporal aggregation step for forcing series "
            "(for example recharge/runoff) and the resulting stress periods."
        ),
        examples=["1 month", "10 day"],
    )
    step_unit: Annotated[TimePeriodUnit | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional forcing/stress-period base time unit used with step_value "
            "when step_value is provided without an inline unit."
        ),
    )
    substeps_per_period: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description=(
            "Number of solver time steps within each stress period. "
            "Higher values improve transient accuracy (e.g., 30 for daily "
            "substeps inside monthly stress periods)."
        ),
    )
    coverage_policy: Annotated[CoveragePolicy, Profile.DEV] = Field(
        default="error",
        description=(
            "Behavior when recharge does not fully cover the declared simulation "
            "window bounds [start_datetime, end_datetime]: "
            "'error' raises, 'warn' emits a warning, 'ignore' skips checks."
        ),
    )

    @model_validator(mode="after")
    def _validate_window_order(self):
        explicit_unit_raw: str | None = None
        if self.step_unit is not None and str(self.step_unit).strip() != "":
            explicit_unit_raw = str(self.step_unit).strip()

        scalar, resolved_unit = parse_scalar_and_unit(
            self.step_value,
            location="simulation.time.step_value",
            default_unit=explicit_unit_raw or "day",
        )
        if isinstance(scalar, bool):
            raise ValueError("simulation.time.step_value must be a positive integer.")
        try:
            scalar_float = float(scalar)
        except Exception as exc:
            raise ValueError("simulation.time.step_value must be a positive integer.") from exc
        if not scalar_float.is_integer() or scalar_float <= 0:
            raise ValueError("simulation.time.step_value must be a positive integer.")
        parsed_step_unit = _coerce_step_unit(resolved_unit)
        if explicit_unit_raw is not None:
            expected_unit = _coerce_step_unit(explicit_unit_raw)
            if parsed_step_unit != expected_unit:
                raise ValueError(
                    "simulation.time.step_value unit conflicts with simulation.time.step_unit."
                )

        object.__setattr__(self, "step_value", int(scalar_float))
        object.__setattr__(self, "step_unit", parsed_step_unit)

        if self.start_datetime is None or self.end_datetime is None:
            raise ValueError(
                "simulation.time.start_datetime and simulation.time.end_datetime "
                "are required when [simulation.time] is declared."
            )
        if (
            self.start_datetime is not None
            and self.end_datetime is not None
            and self.end_datetime < self.start_datetime
        ):
            raise ValueError(
                "simulation.time.end_datetime must be greater than or equal to start_datetime."
            )
        return self


class _ProcessBase(HydroModelBase):
    """Shared fields for simulation process entries.

    Concrete variants below specialize ``type`` to a single literal so the
    enclosing union (``SimulationProcessConfig``) can dispatch via Pydantic's
    standard ``discriminator="type"`` engine.
    """

    id: Annotated[IdentifierStr, Profile.USER] = Field(
        ...,
        description=(
            "User-facing identifier for the process. "
            "This id is required and must be unique within the simulation."
        ),
        examples=["flow_main"],
    )


class FlowProcessConfig(_ProcessBase):
    """``[[simulation.process]]`` entry for a flow process."""

    type: Annotated[Literal["flow"], Profile.USER] = Field(
        default="flow",
        description="Discriminator selecting the 'flow' process family.",
    )
    solvers: Annotated[list[str], Profile.USER] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list of active flow solver names. At least one solver is "
            "required for flow processes."
        ),
    )

    @field_validator("solvers")
    @classmethod
    def _validate_solvers(cls, value: list[str]) -> list[str]:
        cleaned = [solver.strip() for solver in value if solver and solver.strip()]
        if not cleaned:
            raise ValueError(
                "simulation.process entries with type='flow' require at least one solver."
            )
        return cleaned

    def validate_registry(self) -> None:
        """Verify the process family is registered. Call explicitly from launcher."""
        registered = get_solver_registry_provider().known_process_types()
        if "flow" not in registered:
            raise ValueError(
                f"Unknown process type 'flow'. Registered types: "
                f"{', '.join(sorted((*registered, 'mesh')))}."
            )


class TransportProcessConfig(_ProcessBase):
    """``[[simulation.process]]`` entry for a transport process."""

    type: Annotated[Literal["transport"], Profile.USER] = Field(
        default="transport",
        description="Discriminator selecting the 'transport' process family.",
    )
    solvers: Annotated[list[str], Profile.USER] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list of active transport solver names. At least one "
            "solver is required for transport processes."
        ),
    )

    @field_validator("solvers")
    @classmethod
    def _validate_solvers(cls, value: list[str]) -> list[str]:
        cleaned = [solver.strip() for solver in value if solver and solver.strip()]
        if not cleaned:
            raise ValueError(
                "simulation.process entries with type='transport' require at least one solver."
            )
        return cleaned

    def validate_registry(self) -> None:
        """Verify the process family is registered. Call explicitly from launcher."""
        registered = get_solver_registry_provider().known_process_types()
        if "transport" not in registered:
            raise ValueError(
                f"Unknown process type 'transport'. Registered types: "
                f"{', '.join(sorted((*registered, 'mesh')))}."
            )


class MeshProcessConfig(_ProcessBase):
    """``[[simulation.process]]`` entry for a mesh orchestration process."""

    type: Annotated[Literal["mesh"], Profile.USER] = Field(
        default="mesh",
        description="Discriminator selecting the 'mesh' orchestration family.",
    )
    backend: Annotated[Literal["catchment"], Profile.USER] = Field(
        default="catchment",
        description=(
            "Backend used by the mesh process. Currently only 'catchment' is "
            "supported (delegates to the [mesh_catchment] runtime)."
        ),
    )
    solvers: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        max_length=0,
        description=(
            "Reserved for future use. Mesh processes must not declare solvers; "
            "set 'backend' instead."
        ),
    )

    def validate_registry(self) -> None:
        """No-op: mesh is always supported when the launcher is wired."""
        return


SimulationProcessConfig: TypeAlias = Annotated[
    FlowProcessConfig | TransportProcessConfig | MeshProcessConfig,
    Field(
        discriminator="type",
        description=(
            "Discriminated union of simulation processes tagged by the 'type' family "
            "(flow, transport, mesh)."
        ),
    ),
]


def _coerce_process_entry(value: Any) -> Any:
    """Normalize dict entries before discriminator dispatch (lowercase type)."""
    if isinstance(value, dict):
        payload = dict(value)
        raw_type = payload.get("type")
        if isinstance(raw_type, str):
            payload["type"] = raw_type.strip().lower()
        return payload
    return value


class SimulationConfig(HydroModelBase):
    """Minimal orchestration block declared under ``[simulation]``."""

    @classmethod
    def transient(
        cls,
        *,
        time: tuple[str, str, object],
        flow: str = "modflow_nwt",
        transport: str | None = None,
        name: str = "",
        **overrides,
    ) -> SimulationConfig:
        """SimulationConfig with a transient time window and declared solvers."""
        start, end, step = time
        processes: list[Any] = [FlowProcessConfig(id="flow_main", solvers=[flow])]
        if transport is not None:
            processes.append(
                TransportProcessConfig(
                    id="transport_main",
                    solvers=[transport],
                )
            )
        return cls(
            name=name,
            time=SimulationTimeConfig(
                start_datetime=start,
                end_datetime=end,
                step_value=step,
            ),
            process=processes,
            **overrides,
        )

    @classmethod
    def steady(
        cls,
        *,
        flow: str = "modflow_nwt",
        start: str = "2000-01-01",
        end: str = "2000-12-31",
        step: object = "1 year",
        name: str = "",
        **overrides,
    ) -> SimulationConfig:
        """SimulationConfig for a steady-state single flow run."""
        return cls.transient(
            time=(start, end, step),
            flow=flow,
            name=name,
            **overrides,
        )

    name: Annotated[str, Profile.USER] = Field(
        default="",
        description=(
            "Human-readable simulation name and the run's identity. When empty, "
            "derived from the TOML filename at load time (run_steady_nwt.toml -> "
            "steady_nwt); a programmatic run without a name gets a deterministic "
            "memorable slug."
        ),
        examples=["cheze_baseline"],
    )
    tags: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Free-text tags attached at registration; editable later via 'hmp tag'.",
    )
    if_exists: Annotated[
        Literal["replace", "fail", "version"],
        Profile.USER,
    ] = Field(
        default="version",
        description=(
            "Behavior when registering a simulation whose ``name`` already exists "
            "in this project. ``version`` (default) mints the next ``stem.vN`` and "
            "keeps every run addressable; ``replace`` trashes the predecessor "
            "(restorable) and takes the name; ``fail`` raises an error."
        ),
    )
    description: Annotated[str, Profile.USER] = Field(
        default="",
        description="Short free-text description of the simulation intent.",
    )
    scientific_objective: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Scientific objective used for catalog and ML stratification.",
    )
    contact_email: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Contact email for the simulation metadata.",
    )
    doi: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="DOI or reference identifier for the simulation metadata.",
    )
    study_area_name: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Human-readable study area name.",
    )
    outlet_x: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Outlet X coordinate in the project CRS units.",
    )
    outlet_y: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Outlet Y coordinate in the project CRS units.",
    )
    time: Annotated[SimulationTimeConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional canonical simulation window used to align solver temporal "
            "settings and validate forcing coverage. Required for launcher "
            "flow processes and for runtime features that explicitly consume "
            "simulation-window dates."
        ),
    )
    process: Annotated[list[SimulationProcessConfig], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Ordered list of requested processes loaded from "
            "[[simulation.process]]. At most one process per type is supported."
        ),
    )
    results: Annotated[ResultsConfig, Profile.DEV] = Field(
        default_factory=ResultsConfig,
        description=(
            "Results storage and export configuration loaded from "
            "[simulation.results]. Controls Catalog, derived variables, "
            "and automated exports."
        ),
    )
    rng_seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=0,
        description=(
            "Master RNG seed for the simulation. When set, every stochastic "
            "consumer (mesh point sampling, synthetic forcing, ...) derives "
            "its own deterministic sub-seed via "
            "``hydromodpy.core.rng.RngManager``. Persisted in "
            "``runs_environment.rng_seed`` so the run can be re-executed "
            "from the catalog snapshot."
        ),
    )

    @field_validator("process", mode="before")
    @classmethod
    def _normalize_process_entries(cls, value: object) -> object:
        if isinstance(value, list):
            return [_coerce_process_entry(entry) for entry in value]
        return value

    @field_validator("process")
    @classmethod
    def _validate_unique_process_types(cls, value: list[Any]) -> list[Any]:
        seen_types: set[str] = set()
        for process_cfg in value:
            if process_cfg.type in seen_types:
                raise ValueError(
                    "At most one process of each type is supported. "
                    f"Duplicate '{process_cfg.type}' process found."
                )
            seen_types.add(process_cfg.type)
        return value

    def has_processes(self) -> bool:
        """Return True when the simulation explicitly declares processes."""
        return bool(self.process)
