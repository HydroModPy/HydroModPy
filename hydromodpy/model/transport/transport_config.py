"""Pydantic configuration model for transport-process definitions.

``[transport]`` holds one table per transport solver, under the name the
registry serves: ``[transport.modflow6]``, ``[transport.modflow6_prt]``,
``[transport.mt3dms]`` and ``[transport.modpath]``. There is no ``parameters``
level under the table name, and a table is checked by the parameter class of
that solver while the file is read, the way ``[solver.<name>]`` is. The runner
reads the block of a run with ``options_of(name)`` and hands its values to the
class of the engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.units.types import DurationDays


class ModpathParametersConfig(HydroModelBase):
    """Configuration payload for the Modpath transport solver."""

    #: The table is experimental. The walkers read this mark as the mark of a field.
    stability: ClassVar[str] = "experimental"

    zone_partic: Annotated[str, Profile.USER] = Field(
        default="domain",
        description=(
            "Where particles are released: 'domain' (every active cell), "
            "'seepage_clip' (the seepage areas of the flow run, clipped to the "
            "watershed), or the path of a raster that marks the release cells."
        ),
    )
    track_dir: Annotated[Literal["forward", "backward"], Profile.USER] = Field(
        default="forward",
        description=(
            "Direction particles are tracked in: with the flow ('forward') or against "
            "it ('backward', from where water leaves back to where it entered)."
        ),
    )
    bore_depth: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        description="Optional bore depth list used for vertical particle injection.",
    )
    cell_div: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Number of particles per axis in each cell.",
        json_schema_extra=field_metadata(unit="-"),
    )
    zloc_div: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="If true, apply vertical subdivision for particle injection.",
    )
    sel_random: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=1,
        description="Optional random downsampling count of injected particles.",
        json_schema_extra=field_metadata(unit="-"),
    )
    sel_slice: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Keep one released particle out of this many, in release order. Unset, "
            "every particle is kept. A count."
        ),
        json_schema_extra={"unit": "-"},
    )

    @field_validator("track_dir", mode="before")
    @classmethod
    def _refuse_custom_track_dir(cls, value: object) -> object:
        """Refuse 'custom': MODPATH would get no starting location from it."""
        if isinstance(value, str) and value.strip().lower() == "custom":
            raise ValueError(
                "track_dir = 'custom' gives MODPATH no starting location, so no "
                "particle would be released. Write 'forward' or 'backward', and mark "
                "the release cells with zone_partic."
            )
        return value


class ConcentrationTransportParametersConfig(HydroModelBase):
    """Configuration payload shared by concentration transport solvers.

    MODFLOW 6 GWT and MODFLOW-NWT MT3DMS keep their own time base, the SI second. Every
    rate here is per second, whatever the unit of the timestep of ``[simulation.time]``,
    and the ``unit`` of each field says it. Only ``[transport.modflow6_prt]`` counts in
    days, with the unit explicit in the key or in the text.
    """

    spc_name: Annotated[str, Profile.USER] = Field(
        default="NO3",
        description=(
            "Name of the transported solute, written in the store under concentration/<spc_name>."
        ),
    )
    sconc_init: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Concentration of the solute in the aquifer at the start of the run, in the "
            "mass per volume unit you choose. The run keeps that unit."
        ),
        json_schema_extra={"unit": "mass/volume"},
    )
    sconc_input: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Concentration of the solute in the recharge water, in the same unit as sconc_init."
        ),
        json_schema_extra={"unit": "mass/volume"},
    )
    disp_long: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Longitudinal dispersivity, in meters.",
        json_schema_extra=field_metadata(unit="m"),
    )
    disp_transh: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Horizontal transverse dispersivity ratio.",
        json_schema_extra=field_metadata(unit="-"),
    )
    disp_transv: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description="Vertical transverse dispersivity ratio.",
        json_schema_extra=field_metadata(unit="-"),
    )
    diffu_coeff: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description=(
            "Molecular diffusion coefficient in m2/s. The MODFLOW 6 GWT backend "
            "runs on the SI SECONDS clock, so this value is consumed per second "
            "(a per-day value is ~86400x too large)."
        ),
        json_schema_extra=field_metadata(unit="m2/s"),
    )
    react_order: Annotated[Literal[None, 0, 1], Profile.DEV] = Field(
        default=None,
        description=(
            "Reaction order for MODFLOW 6 GWT and MT3DMS: None (no decay), 0 "
            "(zero-order, constant rate in mass per volume per second), or 1 "
            "(first-order, proportional to concentration, in 1/s). Rates are on "
            "the SI SECONDS clock used by the GWT backend."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    scheme: Annotated[Literal["upstream", "central", "TVD"], Profile.DEV] = Field(
        default="upstream",
        description=(
            "Advection scheme for MODFLOW 6 GWT. upstream: robust but diffusive "
            "(default). central: least diffusive, may oscillate. TVD: accurate "
            "sharp fronts (Ogata-Banks)."
        ),
    )
    rate_decay: Annotated[float, Profile.DEV] = Field(
        default=0.0,
        description=(
            "Decay rate on the SI SECONDS clock used by the MODFLOW 6 GWT backend: "
            "1/s for first-order (react_order=1), mass per volume per second for "
            "zero-order (react_order=0). A per-day value is ~86400x too large and "
            "annihilates the solute. Can be overridden at runtime."
        ),
        json_schema_extra=field_metadata(unit="1/s, or mass/volume/s"),
    )
    porosity: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        le=1.0,
        json_schema_extra={"unit": "-"},
        description=(
            "Effective (total) porosity [-], the dimensionless volume of interconnected "
            "pores per bulk volume. Drives MST pore volume and pore velocity. When omitted, "
            "the flow model specific yield is used, which underestimates pore volume and "
            "biases transit times low."
        ),
    )
    plot_conc: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Enable concentration plotting outputs.",
    )

    @field_validator("spc_name")
    @classmethod
    def _refuse_a_blank_or_slashed_solute_name(cls, value: str) -> str:
        """Refuse a name the store could not file under concentration/<spc_name>."""
        if not value.strip():
            raise ValueError(
                "spc_name names the solute in the store, under concentration/<spc_name>, "
                "and cannot be blank."
            )
        if "/" in value:
            raise ValueError(
                "spc_name is one segment of the store path concentration/<spc_name>, "
                f"and cannot carry a '/', got {value!r}."
            )
        return value


class Modflow6PrtParametersConfig(HydroModelBase):
    """Configuration payload for MODFLOW 6 PRT particle tracking."""

    #: The table is experimental. The walkers read this mark as the mark of a field.
    stability: ClassVar[str] = "experimental"

    release_zone: Annotated[str, Profile.USER] = Field(
        default="domain",
        description=(
            "Cells particles are released from: 'domain' (every active cell), "
            "'domain_nonriver' (the same without river cells), 'upstream' (the highest "
            "cells), 'upstream_nonriver', 'river', 'outlet' (the lowest cells), or "
            "'custom' (the cells particle_cell_ids lists)."
        ),
    )
    upstream_top_quantile: Annotated[float, Profile.USER] = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description=(
            "Top-elevation quantile used by upstream release zones. A value of 0.90 "
            "selects cells in the highest 10 percent of active cell-top elevations."
        ),
        json_schema_extra={"unit": "-"},
    )
    outlet_bottom_quantile: Annotated[float, Profile.USER] = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description=(
            "Bottom-elevation quantile used by the 'outlet' release zone. A value of "
            "0.10 selects cells in the lowest 10 percent of active cell-top elevations."
        ),
        json_schema_extra={"unit": "-"},
    )
    track_dir: Annotated[Literal["forward"], Profile.USER] = Field(
        default="forward",
        description=(
            "Direction particles are tracked in. MODFLOW 6 PRT tracks with the flow "
            "only, so 'forward' is the one value."
        ),
    )
    porosity: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        le=1.0,
        json_schema_extra={"unit": "-"},
        description=(
            "Effective (total) porosity [-] for particle tracking (v = q / porosity). "
            "When omitted, the flow model specific yield is used where positive, with a "
            "warning, since specific yield underestimates pore volume."
        ),
    )
    local_z: Annotated[float, Profile.USER] = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Height of the release point inside its cell, from 0 at the bottom to 1 at the top."
        ),
        json_schema_extra={"unit": "-"},
    )
    particle_cell_ids: Annotated[
        list[int] | None, Profile.USER, VisibleWhen("release_zone", "custom")
    ] = Field(
        default=None,
        description=("Cells to release particles from, by their index in the mesh counted from 0."),
        json_schema_extra=field_metadata(unit="-"),
    )
    max_particles: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Most release cells kept after the zone is selected; the kept cells are "
            "spread over the zone. Unset, every cell of the zone releases. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    sel_slice: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=1,
        description=(
            "Keep one release cell out of this many, in cell order, before max_particles "
            "applies. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    release_times: Annotated[list[DurationDays] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Times particles are released at, from the start of the run. A bare number is "
            "in days; a text carries its unit, such as '6 months'. Unset, they are released "
            "once at the start."
        ),
        examples=[[0.0], ["1 year"]],
        json_schema_extra=field_metadata(
            unit="day",
            renamed_from=["transport.modflow6prt.parameters.release_times_days"],
        ),
    )
    track_times: Annotated[list[DurationDays] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Times the particle positions are written at, from the start of the run. A bare "
            "number is in days; a text carries its unit."
        ),
        json_schema_extra=field_metadata(
            unit="day",
            renamed_from=["transport.modflow6prt.parameters.track_times_days"],
        ),
    )
    track_time_step: Annotated[DurationDays | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Spacing of regular output times from 0 to stop_time. A bare number is in days; "
            "a text carries its unit. track_times wins over it. It needs stop_time."
        ),
        examples=[30.0, "1 month"],
        json_schema_extra=field_metadata(
            unit="day",
            renamed_from=["transport.modflow6prt.parameters.track_time_step_days"],
        ),
    )
    stop_time: Annotated[DurationDays | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Time all particles stop at, from the start of the run. A bare number is in "
            "days; a text carries its unit, such as '100 years'."
        ),
        examples=[36500.0, "100 years"],
        json_schema_extra=field_metadata(
            unit="day",
            renamed_from=["transport.modflow6prt.parameters.stop_time_days"],
        ),
    )
    stop_travel_time: Annotated[DurationDays | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Longest time a particle may travel, from its release. A bare number is in "
            "days; a text carries its unit."
        ),
        json_schema_extra=field_metadata(
            unit="day",
            renamed_from=["transport.modflow6prt.parameters.stop_travel_time_days"],
        ),
    )
    extend_tracking: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Keep tracking particles after the last flow time step, with the last flow "
            "field, when MODFLOW 6 allows it."
        ),
    )
    dry_tracking_method: Annotated[Literal["drop", "stop", "stay"], Profile.DEV] = Field(
        default="drop",
        description="MF6 PRT behavior for dry-but-active cells.",
    )
    exit_solve_tolerance: Annotated[float, Profile.DEV] = Field(
        default=1.0e-5,
        gt=0.0,
        description=(
            "PRT generalized Pollock exit solve tolerance. Matches the MF6 "
            "prt-prp.dfn default (1e-5), which works well for many problems."
        ),
    )
    write_track_csv: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Write the particle track CSV file. HydroModPy reads the tracks from it, so "
            "turning it off leaves the run with no particle result."
        ),
    )
    write_track_binary: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Write the binary particle track file of MODFLOW 6 as well.",
    )


PARAMETER_TABLES: dict[str, type[HydroModelBase]] = {
    "modflow6": ConcentrationTransportParametersConfig,
    "modflow6_prt": Modflow6PrtParametersConfig,
    "mt3dms": ConcentrationTransportParametersConfig,
    "modpath": ModpathParametersConfig,
}
"""The parameter class of each transport, keyed by its registry name.

The name is the one a TOML writes as ``[transport.<name>]`` and in
``[[simulation.process]].solvers``, and the one the registry serves. GWT and
MT3DMS share their concentration parameters, so they hold the same class.
"""


def _refused_at(name: str, value: Any, error: ValueError) -> ValidationError:
    """Return *error* as a validation error at the key ``name`` of ``[transport]``."""
    return ValidationError.from_exception_data(
        "TransportConfig",
        [InitErrorDetails(type="value_error", loc=(name,), input=value, ctx={"error": error})],
    )


def _table_errors_under(name: str, exc: ValidationError) -> ValidationError:
    """Return the errors of table *name* placed under its key, so a refusal names the table."""
    details: list[InitErrorDetails] = []
    for error in exc.errors():
        loc = (name, *error["loc"])
        if error["type"] == "value_error":
            details.append(
                InitErrorDetails(
                    type="value_error", loc=loc, input=error["input"], ctx=error.get("ctx", {})
                )
            )
        else:
            details.append(
                InitErrorDetails(
                    type=PydanticCustomError(error["type"], error["msg"]),
                    loc=loc,
                    input=error["input"],
                )
            )
    return ValidationError.from_exception_data("TransportConfig", details)


@cache
def _default_dump(table: type[BaseModel]) -> dict[str, Any]:
    """Return the parameters of *table* at their defaults, as a dict to compare with."""
    return table().model_dump()


def _table_is_untouched(table: BaseModel) -> bool:
    """Whether *table* was given no key and holds its defaults: a table nobody wrote."""
    return not table.model_fields_set and table.model_dump() == _default_dump(type(table))


class TransportConfig(HydroModelBase):
    """The ``[transport]`` section: one table per transport solver the document names.

    Every key of the section is the registry name of a transport of this
    installation, ``[transport.modflow6]`` for instance, and holds its
    parameters without a ``parameters`` level. A name nothing serves is refused
    with the names served. A table of a transport that does not run is accepted
    and checked too, because a run sealed by an earlier version wrote all four,
    and the drift of a replay reads them as it ran.
    """

    _options: dict[str, BaseModel] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _read_the_transport_tables(
        cls, data: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> TransportConfig:
        """Validate each ``[transport.<name>]`` table by the parameter class of that solver.

        A key that names a solver checks by the class of its parameters; a name
        nothing serves is refused with the names this section holds.
        """
        tables: dict[str, BaseModel] = {}
        if isinstance(data, Mapping):
            for key, value in data.items():
                tables[str(key)] = cls._validated_table(str(key), value, info)
            data = {}
        validated = handler(data)
        # Through the private store, not setattr: a frozen copy validated again
        # settles to the tables it already holds.
        held = {**validated.__pydantic_private__.get("_options", {}), **tables}
        validated.__pydantic_private__["_options"] = {
            name: table for name, table in sorted(held.items()) if not _table_is_untouched(table)
        }
        return validated

    @classmethod
    def _validated_table(cls, name: str, value: Any, info: ValidationInfo) -> BaseModel:
        """Return table *name* validated by its parameter class, refused at its own key."""
        try:
            check_registered_name(name, PARAMETER_TABLES, key=f"transport.{name}")
            options_cls: type[BaseModel] = PARAMETER_TABLES[name]
        except ValueError as exc:
            raise _refused_at(name, value, exc) from None
        if isinstance(value, options_cls):
            return value
        try:
            return options_cls.model_validate(value, context=info.context)
        except ValidationError as exc:
            raise _table_errors_under(name, exc) from None

    @model_serializer(mode="wrap")
    def _write_the_transport_tables(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, Any]:
        """Write each held table flat under its name, as ``[transport.modflow6]``."""
        dumped = handler(self)
        only_written = info.exclude_unset or info.exclude_defaults
        tables = self.written_tables() if only_written else self.held_tables()
        for name, table in tables.items():
            dumped[name] = table.model_dump(
                mode=info.mode,
                by_alias=bool(info.by_alias),
                exclude_unset=info.exclude_unset,
                exclude_defaults=info.exclude_defaults,
                exclude_none=info.exclude_none,
            )
        return dumped

    @classmethod
    def named_tables(cls, *, shipped_only: bool) -> dict[str, type[BaseModel]]:
        """Return the parameter class of each transport solver that declares one, by name.

        *shipped_only* keeps the transports this build ships, the four of this
        build. The generic readers of a model (the schema, the template, the
        parameter pages) read the tables here, as they read ``[solver.<name>]``.
        """
        return dict(PARAMETER_TABLES)

    def held_tables(self) -> dict[str, BaseModel]:
        """Return the tables this section holds, the ones a key was given in."""
        return dict(self._options)

    def written_tables(self) -> dict[str, BaseModel]:
        """Return the held tables a key was given in, without a table at its defaults."""
        return {
            name: table for name, table in self._options.items() if not _table_is_untouched(table)
        }

    def options_of(self, name: str) -> BaseModel:
        """Return the parameters of transport solver *name*, as validated, or its defaults.

        Raises
        ------
        ValueError
            When nothing serves *name*.
        """
        held = self._options.get(name)
        if held is not None:
            return held
        check_registered_name(name, PARAMETER_TABLES, key=f"transport.{name}")
        options_cls = PARAMETER_TABLES[name]
        return options_cls()


__all__ = [
    "ConcentrationTransportParametersConfig",
    "Modflow6PrtParametersConfig",
    "ModpathParametersConfig",
    "TransportConfig",
]
