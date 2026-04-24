"""Declarative simulation configuration models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units import normalize_time_unit, parse_scalar_and_unit
from hydromodpy.results.config import ResultsConfig
from hydromodpy.solver.base.registry import known_process_types

_VALID_STEP_UNITS = {"hour", "day", "month", "year"}


def _normalize_step_unit_token(raw_step_unit: object) -> Literal["hour", "day", "month", "year"]:
    token = str(raw_step_unit).strip().lower()
    if token == "":
        raise ValueError("simulation.time.step_unit cannot be empty.")
    if token in {"m", "mo", "mon", "month", "months"}:
        return "month"

    try:
        canonical = normalize_time_unit(token)
    except ValueError as exc:
        raise ValueError(
            "simulation.time.step_unit must be one of: hour, day, month, year."
        ) from exc

    map_to_step_unit = {
        "hours": "hour",
        "days": "day",
        "years": "year",
    }
    step_unit = map_to_step_unit.get(canonical)
    if step_unit is None:
        raise ValueError("simulation.time.step_unit must be one of: hour, day, month, year.")
    return step_unit


def _normalize_step_value_scalar(raw_step_value: object) -> int:
    if isinstance(raw_step_value, bool):
        raise ValueError("simulation.time.step_value must be a positive integer.")
    try:
        parsed = float(raw_step_value)
    except Exception as exc:
        raise ValueError("simulation.time.step_value must be a positive integer.") from exc
    if not parsed.is_integer() or parsed <= 0:
        raise ValueError("simulation.time.step_value must be a positive integer.")
    return int(parsed)


def _parse_step_spec(
    *,
    raw_step_value: object,
    raw_step_unit: object,
) -> tuple[int, Literal["hour", "day", "month", "year"]]:
    explicit_unit_raw: str | None = None
    if raw_step_unit is not None and str(raw_step_unit).strip() != "":
        explicit_unit_raw = str(raw_step_unit).strip()

    default_unit = explicit_unit_raw or "day"
    scalar, resolved_unit = parse_scalar_and_unit(
        raw_step_value,
        location="simulation.time.step_value",
        default_unit=default_unit,
    )
    step_value = _normalize_step_value_scalar(scalar)
    parsed_step_unit = _normalize_step_unit_token(resolved_unit)

    if explicit_unit_raw is not None:
        explicit_step_unit = _normalize_step_unit_token(explicit_unit_raw)
        if parsed_step_unit != explicit_step_unit:
            raise ValueError(
                "simulation.time.step_value unit conflicts with simulation.time.step_unit."
            )
    if parsed_step_unit not in _VALID_STEP_UNITS:
        raise ValueError("simulation.time.step_unit must be one of: hour, day, month, year.")
    return step_value, parsed_step_unit


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
        default=1,
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
        step_value, step_unit = _parse_step_spec(
            raw_step_value=self.step_value,
            raw_step_unit=self.step_unit,
        )
        object.__setattr__(self, "step_value", int(step_value))
        object.__setattr__(self, "step_unit", step_unit)

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
        registered = known_process_types()
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
                    depends_on=["flow_main"],
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
