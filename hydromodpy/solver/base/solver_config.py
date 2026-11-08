"""The ``[solver]`` section: the flow solver of a run and the settings of each one.

``solver.backend`` names a registered flow solver, as a string checked against the
registry while the file is read. Every other key of ``[solver]`` that is not one of
the switches below is the name of a flow solver, and holds its settings: the table
``[solver.modflow6]`` is validated by the ``options`` class the MODFLOW 6 adapter
declares. A plugin solver gets its own table the same way, without a patch here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import cache
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
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
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.solver.base.registry import ENTRY_POINT_GROUP, solvers


class FlowSolverOfTheProcess(str):
    """A ``solver.backend`` value taken from the flow process, not written by the file.

    The mark keeps ``backend`` out of the fields the file set, so a later change of
    the flow process moves the backend with it instead of being refused.
    """


def backend_following_the_process(name: str) -> FlowSolverOfTheProcess:
    """Return flow solver *name* marked as derived from the flow process."""
    return FlowSolverOfTheProcess(str(name).strip())


def _registered_flow_solver(value: str) -> str:
    """Return the flow solver *value* names, lower case, or refuse a name nothing serves."""
    cleaned = str(value).strip().lower()
    return check_registered_name(
        cleaned, solvers.names("flow"), key="solver.backend", group=ENTRY_POINT_GROUP
    )


def _options_class(name: str) -> type[BaseModel] | None:
    """Return the settings class flow solver *name* declares, or ``None``."""
    return solvers.get("flow", name).options


@cache
def _default_dump(options: type[BaseModel]) -> dict[str, Any]:
    """Return the settings of *options* at their defaults, as a dict to compare with."""
    return options().model_dump()


def _taken_in_silence(table: BaseModel) -> bool:
    """Whether *table* was given no key and holds its defaults: a table nobody wrote."""
    return not table.model_fields_set and table.model_dump() == _default_dump(type(table))


def _refused_at(name: str, value: Any, error: ValueError) -> ValidationError:
    """Return *error* as a validation error at the key ``name`` of ``[solver]``."""
    return ValidationError.from_exception_data(
        "SolverConfig",
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
    return ValidationError.from_exception_data("SolverConfig", details)


class SolverConfig(HydroModelBase):
    """The flow solver of a run, its settings, and the switches every backend may read.

    The TOML form is ``backend = "modflow6"``. The settings of a flow solver sit
    under its name, ``[solver.modflow6]``, and are checked by the class it declares
    as ``options``. A table of a solver that does not run is accepted and checked
    too, because a recipe of ``[sites]`` changes the solver on a shared base.

    It also carries the backend-agnostic preprocessing switches both MODFLOW
    backends read, so one TOML key drives both. ``sink_fill`` and
    ``drain_band_depth_m`` both act on the drains of a depressed model top and
    are mutually exclusive.
    """

    backend: Annotated[str, Profile.USER, AfterValidator(_registered_flow_solver)] = Field(
        default="modflow6",
        description=(
            "Flow solver of the run, by its registered name: MODFLOW 6, MODFLOW-NWT, "
            "Boussinesq or a plugin. A name this installation does not serve is refused "
            "with the names it serves."
        ),
        examples=list(solvers.names("flow", shipped_only=True)),
    )
    _options: dict[str, BaseModel] = PrivateAttr(default_factory=dict)
    sink_fill: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Dimensionless. Remove the drain from every cell sitting in a closed "
            "depression of the model top, by setting its DRN conductance to zero. "
            "A closed depression has no outlet, so water reaching it ponds instead "
            "of seeping into a stream, and a drain there invents a discharge point. "
            "The depressions are measured on the solver mesh, by a priority flood "
            "seeded on every cell water can leave the domain through; both MODFLOW "
            "backends read the same mask. This does NOT move the topography: no "
            "elevation is raised, no DEM is rewritten, and every other package sees "
            "the surface it would have seen. Refused when the mask cannot be built. "
            "The depressions are counted on the four shared faces MODFLOW "
            "connects, not on the eight neighbours a raster fill uses: the share of "
            "the mesh flagged is about twice as large on four faces as on eight "
            "neighbours, a factor that is the neighbourhood and nothing else. NOT "
            "SANCTIONED BY ANY SOURCE: no manual, no USGS document and no "
            "guideline removes a discharge boundary where a pit is detected, and "
            "measured here it degrades both scores. The remedy the USGS does "
            "document for the same question is solver.drain_band_depth_m, which "
            "gives every cell a discharge band instead of taking the drain away. "
            "Default false, which drains every cell as before."
        ),
        examples=[False, True],
    )
    drain_bed_thickness_m: Annotated[float, Profile.EXPERT] = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Metres. Thickness of the drain BED in the fallback conductance "
            "C = K * cell_area / bed_thickness, used when no drainage conductance "
            "is declared. A drain bed is the clogging layer at the bottom of a "
            "watercourse, decimetres to a metre; it is NOT the aquifer, and the "
            "layer thickness this used to borrow (tens of metres) has no "
            "physical relation to it. The value matters because it sets how much "
            "head the drain itself imposes to pass the recharge: dh = R * "
            "bed_thickness / K, independent of the cell size. For "
            "R = 439 mm/yr, 30 m gives 4.17 m of head at K = 1e-7 m/s and makes "
            "the drain the limiting resistance over two decades of a "
            "[1e-7, 1e-3] search; 1 m gives 13.9 cm and 0.1 m gives 1.4 cm. In "
            "this method the drain is a seepage face, so it must never limit: K "
            "and the recharge decide where water surfaces, not the boundary "
            "condition. Proportionality to K is preserved either way, so the K/R "
            "invariance the network criterion rests on is untouched. The value 1.0 is a "
            "convention with no measured source: no measurement and no document gives it, and "
            "it is kept as it is so that no earlier result moves. It stays in [solver], whatever the layer of the "
            "other drain keys. Write your own value when you have a measure."
        ),
        examples=[1.0, 0.5, 0.1],
    )
    drain_conductance_floor_m2_s: Annotated[float, Profile.EXPERT] = Field(
        default=1e-12,
        gt=0.0,
        description=(
            "m2/s. Floor applied to every DRN conductance, whether declared or "
            "derived from hk. It exists for degenerate cells only, a zero-thickness "
            "or zero-conductivity cell whose formula would divide by zero or emit a "
            "zero-conductance drain MODFLOW reads as absent. It is not a physical "
            "choice and moving it does not tune anything: a real conductance on a "
            "real cell is many orders of magnitude above it. Raise it only to make "
            "a degenerate mesh audible."
        ),
    )
    drain_band_depth_m: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Metres. Depth D of the sub-cell discharge band every drain cell gets "
            "instead of a single elevation: the drain sits at top - D/2 and its "
            "conductance is multiplied by top_layer_thickness / D. The multiplier "
            "is the thickness and not the cell area because the conductance it "
            "scales is already Kv*A/b, so scaling by b/D gives Kv*A/D, which is "
            "CDRN exactly; scaling by A/D would give an m3/s where a conductance "
            "is m2/s, too high by A/b. The cell therefore starts "
            "discharging before the head reaches its mean elevation, and discharges "
            "harder the higher the head climbs into the band. This answers the one "
            "question the USGS documents about a model top, that the land inside a "
            "cell is not flat: UZF1 exposes the same depth as SURFDEP, 'the average "
            "undulation depth within a finite-difference cell', and MODFLOW 6 carries "
            "it into DRN as DDRN, with HDRN = land surface - DDRN/2 and "
            "CDRN = Kv*A/DDRN. MODFLOW 6 solves its DDRN band with a smooth "
            "(linear then cubic) curve; the option here is the piecewise equivalent "
            "of the same idea, applied identically by both MODFLOW backends, so a "
            "later switch to the native smooth form is a documented refinement and "
            "not a surprise. It does NOT move the topography: no elevation is "
            "raised, no DEM is rewritten, and every other package sees the surface "
            "it would have seen. The seepage criterion is the one reader that "
            "cannot: a banded cell discharges at top - D/2 and never climbs back "
            "to top, so the mask follows the band and the run persists D in its "
            "store for every figure drawn afterwards. It classifies no cell: "
            "every drain cell gets the "
            "same band, so nothing has to be sorted into artefact and real. Pick D "
            "the way Feinstein et al. 2020 (Groundwater 58:524-534, "
            "doi:10.1111/gwat.12931) do, from the standard deviation of the fine "
            "land-surface elevations inside a cell; they obtain 0.61 m. Mutually "
            "exclusive with solver.sink_fill, which answers the same question by "
            "removing drains instead. Default 0.0: one elevation per drain, "
            "unchanged from every earlier run."
        ),
        examples=[0.0, 0.5],
    )

    @field_validator("drain_band_depth_m")
    @classmethod
    def _validate_drain_band_depth(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError(
                f"solver.drain_band_depth_m must be a finite depth in metres, got {value!r}."
            )
        if value < 0.0:
            raise ValueError(
                "solver.drain_band_depth_m is a depth in metres and cannot be negative, "
                f"got {value!r}. Use 0.0 to keep one elevation per drain."
            )
        return value

    @model_validator(mode="after")
    def _refuse_both_depression_remedies(self) -> SolverConfig:
        """Refuse ``sink_fill`` and a discharge band together.

        Both answer the same question, that a cell of the model top is a
        depression, and they answer it in opposite directions: ``sink_fill``
        deletes the discharge of those cells, the band gives every cell a deeper
        one. Run together, ``sink_fill`` would win on exactly the cells the band
        was set for, and the depth would silently do nothing where it matters.
        """
        if self.sink_fill and self.drain_band_depth_m > 0.0:
            raise ValueError(
                "solver.sink_fill and solver.drain_band_depth_m are two opposite "
                "answers to the same question and cannot both be set: sink_fill "
                "removes the discharge of a depressed cell, drain_band_depth_m gives "
                "every cell a discharge band. Keep one."
            )
        return self

    @model_validator(mode="wrap")
    @classmethod
    def _read_the_solver_tables(
        cls, data: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> SolverConfig:
        """Validate each ``[solver.<name>]`` table by the settings class of solver *name*.

        A key that is not a field is the name of a flow solver. A name nothing
        serves is refused with the names served, and a solver that declares no
        settings refuses its table. The table of the running solver is held at its
        defaults when the file writes none, so a dotted path reaches it.
        """
        follows = False
        tables: dict[str, BaseModel] = {}
        if isinstance(data, Mapping):
            fields = {key: value for key, value in data.items() if key in cls.model_fields}
            follows = isinstance(fields.get("backend"), FlowSolverOfTheProcess)
            for key, value in data.items():
                if key not in fields:
                    tables[str(key)] = cls._validated_table(str(key), value, info)
            data = fields
        elif isinstance(data, SolverConfig):
            follows = isinstance(data.backend, FlowSolverOfTheProcess)
            if follows:
                object.__setattr__(data, "backend", _registered_flow_solver(data.backend))
        validated = handler(data)
        validated._settle_tables(tables)
        if follows:
            validated.__pydantic_fields_set__.discard("backend")
        return validated

    @classmethod
    def _validated_table(cls, name: str, value: Any, info: ValidationInfo) -> BaseModel:
        """Return table *name* validated by its solver's settings class, refused at its own key."""
        try:
            check_registered_name(
                name, solvers.names("flow"), key=f"solver.{name}", group=ENTRY_POINT_GROUP
            )
            options = _options_class(name)
            if options is None:
                raise ValueError(
                    f"[solver.{name}] holds settings, and the flow solver {name!r} declares "
                    "none to read them. Remove the table."
                )
        except ValueError as exc:
            raise _refused_at(name, value, exc) from None
        if isinstance(value, options):
            return value
        try:
            return options.model_validate(value, context=info.context)
        except ValidationError as exc:
            raise _table_errors_under(name, exc) from None

    def _settle_tables(self, written: Mapping[str, BaseModel]) -> None:
        """Hold the running solver's table, and every table a key was given in."""
        held = {**self._options, **written}
        running = self.backend
        if running not in held:
            options = _options_class(running)
            if options is not None:
                held[running] = options()
        # Through the private store, not setattr: a frozen copy validated again
        # settles to the tables it already holds.
        self.__pydantic_private__["_options"] = {
            name: table
            for name, table in sorted(held.items())
            if name == running or not _taken_in_silence(table)
        }

    @model_serializer(mode="wrap")
    def _write_the_solver_tables(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, Any]:
        """Write each held table flat under its name, as ``[solver.modflow6]``."""
        dumped = handler(self)
        only_written = info.exclude_unset or info.exclude_defaults
        tables = self.written_tables() if only_written else self._options
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
        """Return the settings class of each flow solver that declares one, by name.

        *shipped_only* keeps the solvers this build ships, so a schema or a page
        does not depend on what is installed beside it. The generic readers of a
        model (the schema, the template, the parameter pages) read the tables here.
        """
        found: dict[str, type[BaseModel]] = {}
        for name in solvers.names("flow", shipped_only=shipped_only):
            options = _options_class(name)
            if options is not None:
                found[name] = options
        return found

    def held_tables(self) -> dict[str, BaseModel]:
        """Return the tables this section holds: the running solver's, and the others written."""
        return dict(self._options)

    def written_tables(self) -> dict[str, BaseModel]:
        """Return the held tables a key was given in, or that left their defaults."""
        return {
            name: table for name, table in self._options.items() if not _taken_in_silence(table)
        }

    def options_of(self, name: str) -> BaseModel:
        """Return the settings of flow solver *name*, as validated, or its defaults.

        Raises
        ------
        ValueError
            When nothing serves *name*, or the solver declares no settings.
        """
        held = self._options.get(name)
        if held is not None:
            return held
        check_registered_name(
            name, solvers.names("flow"), key=f"solver.{name}", group=ENTRY_POINT_GROUP
        )
        options = _options_class(name)
        if options is None:
            raise ValueError(f"The flow solver {name!r} declares no settings.")
        return options()

    @property
    def backend_name(self) -> str:
        """The registered name of the flow solver, as ``solvers.get("flow", name)`` reads it."""
        return self.backend
