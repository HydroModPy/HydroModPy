"""Declarative simulation configuration models."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase, write_resolved
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    CoveragePolicy,
    IdentifierStr,
    TimePeriodUnit,
)
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.time.window import reject_invalid_step_value_spec
from hydromodpy.core.units import normalize_time_unit, parse_scalar_and_unit
from hydromodpy.solver.base.registry import ENTRY_POINT_GROUP, solvers
from hydromodpy.solver.base.results_config import ResultsConfig

_VERSION_SUFFIX_RE = re.compile(r"\.v(\d+)$")
"""The ``.vN`` a run directory takes from its reservation."""

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
            "(for example recharge/runoff) and the resulting stress periods. "
            "Not read by a steady run (flow.flow_regime = 'steady'), which is one "
            "stress period over the whole window, its forcings averaged over it."
        ),
        examples=["1 month", "10 day"],
    )
    step_unit: Annotated[TimePeriodUnit | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit of a bare-number step_value: the length of the stress periods and "
            "of the forcing steps."
        ),
        json_schema_extra={
            "value_docs": {
                "hour": (
                    "Treats step_value as whole hours, for sub-daily forcing and stress periods."
                ),
                "day": (
                    "Treats step_value as whole days, the common granularity "
                    "for daily forcing series."
                ),
                "month": (
                    "Treats step_value as calendar months, so the step length varies by month."
                ),
                "year": (
                    "Treats step_value as calendar years, so the step length "
                    "varies with leap years."
                ),
            }
        },
    )
    substeps_per_period: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description=(
            "Number of solver time steps within each stress period, the one knob "
            "that buys transient accuracy. The default of 1 integrates a whole "
            "period in a single backward-Euler step, which is not a neutral "
            "choice: on a seasonally recharged hillslope drained by DRN cells it "
            "moves the monthly discharge by 4 to 28 % against a refined run, "
            "across the whole plausible bedrock range, and a calibration scored "
            "on discharge absorbs that into the fitted parameters. The right "
            "count compares the aquifer response time `tau = L^2 S / (K b)` with "
            "the period length, and the solver cost is linear in it; 30 gives "
            "daily steps inside monthly periods. Consumed by the MODFLOW "
            "backends as DIS NSTP / TDIS nstp, and by the Boussinesq backend, "
            "which solves each period in as many backward-Euler steps of equal "
            "length. Every solver stores one result per period: the head at the "
            "end of the period and each flux as the mean of its steps, weighted "
            "by their length."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    coverage_policy: Annotated[CoveragePolicy, Profile.USER] = Field(
        default="error",
        description=(
            "What happens to a stress period that a forcing record does not "
            "cover. A sample is the rate of the interval up to the next sample, "
            "and the last sample stands for one step of the record (the median "
            "spacing of its dates). A period that no sample reaches, before the "
            "first date or after the end of the last step, is not covered. "
            "'error' stops the run, 'warn' warns once per record, 'ignore' says "
            "nothing; under 'warn' and 'ignore' the period takes the nearest "
            "sample in time. The rule is the same for a series, a station and a "
            "grid: rain, ETP, recharge, runoff and the declared CSV forcings read "
            "as rates (aggregate = 'mean')."
        ),
        examples=["error", "warn"],
    )

    @model_validator(mode="after")
    def _validate_window_order(self):
        explicit_unit_raw = reject_invalid_step_value_spec(self.step_value, self.step_unit)

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

        write_resolved(self, "step_value", int(scalar_float))
        write_resolved(self, "step_unit", parsed_step_unit)

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

    Concrete variants below specialize ``kind`` to a single literal so the
    enclosing union (``SimulationProcessConfig``) can dispatch via Pydantic's
    standard ``discriminator="kind"`` engine.
    """

    id: Annotated[IdentifierStr, Profile.USER] = Field(
        ...,
        description=(
            "User-facing identifier for the process. "
            "This id is required and must be unique within the simulation."
        ),
        examples=["flow_main"],
    )


class _SolverProcess(_ProcessBase):
    """A process run by solvers: ``flow`` or ``transport``, with a non-empty ``solvers``."""

    @field_validator("solvers", check_fields=False)
    @classmethod
    def _validate_solvers(cls, value: list[str]) -> list[str]:
        """Keep the names written, stripped, each one a registered solver of the process kind."""
        kind = cls.model_fields["kind"].default
        cleaned = [solver.strip() for solver in value if solver and solver.strip()]
        if not cleaned:
            raise ValueError(
                f"simulation.process entries with kind='{kind}' require at least one solver."
            )
        served = solvers.names(kind)
        for name in cleaned:
            check_registered_name(
                name, served, key="simulation.process.solvers", group=ENTRY_POINT_GROUP
            )
        return cleaned


class FlowProcessConfig(_SolverProcess):
    """``[[simulation.process]]`` entry for a flow process."""

    kind: Annotated[Literal["flow"], Profile.USER] = Field(
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


class TransportProcessConfig(_SolverProcess):
    """``[[simulation.process]]`` entry for a transport process."""

    kind: Annotated[Literal["transport"], Profile.USER] = Field(
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
        json_schema_extra=field_metadata(experimental_values=["modpath", "modflow6_prt"]),
    )


class MeshProcessConfig(_ProcessBase):
    """``[[simulation.process]]`` entry for a mesh orchestration process."""

    kind: Annotated[Literal["mesh"], Profile.USER] = Field(
        default="mesh",
        description="Discriminator selecting the 'mesh' orchestration family.",
    )
    backend: Annotated[Literal["catchment"], Profile.USER] = Field(
        default="catchment",
        description=(
            "How the mesh process builds its mesh. 'catchment' is the one value: it "
            "builds the mesh that [mesh] describes."
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


SimulationProcessConfig: TypeAlias = Annotated[
    FlowProcessConfig | TransportProcessConfig | MeshProcessConfig,
    Field(
        discriminator="kind",
        description=(
            "Discriminated union of simulation processes tagged by the 'kind' family "
            "(flow, transport, mesh)."
        ),
    ),
]


def _coerce_process_entry(value: Any) -> Any:
    """Normalize dict entries before discriminator dispatch (lowercase kind)."""
    if isinstance(value, dict):
        payload = dict(value)
        raw_kind = payload.get("kind")
        if isinstance(raw_kind, str):
            payload["kind"] = raw_kind.strip().lower()
        return payload
    return value


class SimulationConfig(HydroModelBase):
    """Minimal orchestration block declared under ``[simulation]``."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "study_area_name": "name the catchment in [site] name, and its readable name in [site] label.",
        "outlet_x": "the outlet is geographic.catchment.x_outlet, read by the delineation.",
        "outlet_y": "the outlet is geographic.catchment.y_outlet, read by the delineation.",
    }

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
            "memorable slug. It never carries a .vN suffix: the version is given by "
            "the disk when the run is reserved."
        ),
        examples=["cheze_baseline"],
    )
    tags: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Free-text tags attached at registration; editable later via 'hmp catalog tag'.",
    )
    if_exists: Annotated[Literal["fail", "version"], Profile.USER] = Field(
        default="version",
        description=(
            "What a run does when its name is already taken in this project. "
            "``version`` (default) writes the run under the next free ``stem.vN`` and "
            "keeps every run addressable; ``fail`` stops before the run starts. A name is never "
            "reused, so a run is never replaced: delete the old one with "
            "hmp catalog delete."
        ),
        json_schema_extra={
            "value_docs": {
                "version": "Write the run under the next free <name>.vN.",
                "fail": "Refuse to start when the name is taken.",
            }
        },
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
            "[[simulation.process]]. At most one process per kind is supported."
        ),
    )
    results: Annotated[ResultsConfig, Profile.USER] = Field(
        default_factory=ResultsConfig,
        description=(
            "Results storage loaded from [simulation.results]: what the run writes "
            "to the catalog, whether the raw solver files are kept, and how much of "
            "the per-cell budget the run keeps."
        ),
    )
    rng_seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=0,
        description=(
            "Master RNG seed for the simulation. When set, every stochastic "
            "consumer (mesh point sampling, synthetic forcing, ...) derives "
            "its own deterministic sub-seed via "
            "``hydromodpy.core.state.rng.RngManager``. Persisted in "
            "``runs_environment.rng_seed`` so the run can be re-executed "
            "from the catalog snapshot."
        ),
        json_schema_extra={"unit": "-"},
    )

    @field_validator("name")
    @classmethod
    def _refuse_version_suffix(cls, value: str) -> str:
        """Refuse a name that carries ``.vN``: the version is given by the disk."""
        match = _VERSION_SUFFIX_RE.search(value)
        if match:
            stem = value[: match.start()]
            raise ValueError(
                f"[simulation] name = {value!r} carries a version. A version is given "
                f"by the disk when the run is reserved, never written by hand: write "
                f"name = {stem!r}. To continue runs/{value}, run hmp run --resume {value}."
            )
        return value

    @field_validator("if_exists", mode="before")
    @classmethod
    def _refuse_replace(cls, value: object) -> object:
        """Refuse ``if_exists = "replace"`` with what to write instead."""
        if value == "replace":
            raise ValueError(
                "if_exists = 'replace' is gone: it moved the earlier run to the trash and "
                "wrote a new version anyway. Write 'version' (the default) or 'fail', and "
                "delete a run with hmp catalog delete."
            )
        return value

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
            if process_cfg.kind in seen_types:
                raise ValueError(
                    "At most one process of each kind is supported. "
                    f"Duplicate '{process_cfg.kind}' process found."
                )
            seen_types.add(process_cfg.kind)
        return value

    def has_processes(self) -> bool:
        """Return True when the simulation explicitly declares processes."""
        return bool(self.process)
