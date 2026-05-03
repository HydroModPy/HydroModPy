"""Declarative simulation configuration models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import normalize_time_unit, parse_scalar_and_unit
from hydromodpy.simulation._solver_protocol import get_solver_registry_provider
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


def _coerce_step_unit(token: str) -> Literal["hour", "day", "month", "year"]:
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

    model_config = ConfigDict(extra="forbid")

    start_datetime: Annotated[datetime | None, Profile.USER] = Field(
        default=None,
        description=(
            "Simulation window lower datetime bound used by launcher-level "
            "time alignment and forcing checks."
        ),
    )
    end_datetime: Annotated[datetime | None, Profile.USER] = Field(
        default=None,
        description=(
            "Simulation window upper datetime bound, interpreted as inclusive. "
            "Must be greater than or equal to start_datetime."
        ),
    )
    step_value: Annotated[int | float | str, Profile.USER] = Field(
        default="1 month",
        description=(
            "Forcing/stress-period time-step scalar or inline token '<value> <unit>' "
            "(for example '30 day'). "
            "This controls the temporal aggregation step for forcing series "
            "(for example recharge/runoff) and the resulting stress periods."
        ),
    )
    step_unit: Annotated[Literal["hour", "day", "month", "year"] | None, Profile.USER] = Field(
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
    coverage_policy: Annotated[Literal["error", "warn", "ignore"], Profile.DEV] = Field(
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


class SimulationProcessConfig(HydroModelBase):
    """One requested process entry under ``[[simulation.process]]``."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Profile.USER] = Field(
        description=(
            "User-facing identifier for the process. "
            "This id is required and must be unique within the simulation."
        ),
    )
    type: Annotated[str, Profile.USER] = Field(
        description="Requested process family executed by the launcher.",
    )
    solvers: Annotated[list[str], Profile.USER] = Field(
        min_length=1,
        description=(
            "Ordered list of active solver names for this process. Each listed "
            "solver is executed in order."
        ),
    )

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Process type cannot be empty.")
        registered = get_solver_registry_provider().known_process_types()
        if cleaned not in registered:
            raise ValueError(
                f"Unknown process type '{cleaned}'. "
                f"Registered types: {', '.join(sorted(registered))}."
            )
        return cleaned

    @field_validator("solvers")
    @classmethod
    def _validate_solvers(cls, value: list[str]) -> list[str]:
        cleaned = [solver.strip() for solver in value if solver and solver.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty solver name is required.")
        return cleaned


class SimulationConfig(HydroModelBase):
    """Minimal orchestration block declared under ``[simulation]``."""

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def transient(
        cls,
        *,
        time: tuple[str, str, object],
        flow: str = "modflownwt",
        transport: str | None = None,
        name: str = "",
        **overrides,
    ) -> SimulationConfig:
        """SimulationConfig with a transient time window and declared solvers."""
        start, end, step = time
        processes = [SimulationProcessConfig(id="flow_main", type="flow", solvers=[flow])]
        if transport is not None:
            processes.append(
                SimulationProcessConfig(
                    id="transport_main",
                    type="transport",
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
        flow: str = "modflownwt",
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
        default="", description="Human-readable simulation name."
    )
    run_id: Annotated[str, Profile.USER] = Field(
        default="",
        description=(
            "Run identifier used as the output subfolder name under "
            "results_simulations/. When empty, derived from the TOML "
            "filename at load time (e.g. run_steady_nwt.toml -> steady_nwt)."
        ),
    )
    on_collision: Annotated[
        Literal["replace", "fail", "version"],
        Profile.USER,
    ] = Field(
        default="replace",
        description=(
            "Behavior when registering a simulation whose ``name`` already "
            "exists in this project. ``replace`` soft-replaces (the previous "
            "sim keeps its UUID but loses its name), ``fail`` raises an "
            "error, ``version`` auto-suffixes ``name.v2``, ``name.v3`` ..."
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
            "[simulation.results]. Controls SimulationCatalog, derived variables, "
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

    @field_validator("process")
    @classmethod
    def _validate_unique_process_types(
        cls,
        value: list[SimulationProcessConfig],
    ) -> list[SimulationProcessConfig]:
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
