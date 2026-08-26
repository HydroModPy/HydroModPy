"""Top-level solver selection configuration."""

from __future__ import annotations

import math
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

BUILTIN_BACKENDS: tuple[str, ...] = ("modflow6", "modflow_nwt", "boussinesq")


class _SolverBackendBase(HydroModelBase):
    """Shared base for discriminated solver backend selectors."""


class Modflow6Backend(_SolverBackendBase):
    """Select the MODFLOW 6 flow backend."""

    backend: Annotated[Literal["modflow6"], Profile.USER] = Field(
        default="modflow6",
        description="Discriminator tag selecting the MODFLOW 6 flow backend.",
    )


class ModflowNwtBackend(_SolverBackendBase):
    """Select the MODFLOW-NWT flow backend."""

    backend: Annotated[Literal["modflow_nwt"], Profile.USER] = Field(
        default="modflow_nwt",
        description="Discriminator tag selecting the MODFLOW-NWT flow backend.",
    )


class BoussinesqBackend(_SolverBackendBase):
    """Select the Boussinesq flow backend."""

    backend: Annotated[Literal["boussinesq"], Profile.USER] = Field(
        default="boussinesq",
        description="Discriminator tag selecting the Boussinesq flow backend.",
    )


class CustomBackend(_SolverBackendBase):
    """Plugin-registered flow backend identified by a free-form name.

    The discriminator value is the literal string ``"custom"``; the actual
    backend name lives in ``name``. ``SolverConfig.validate_registry()``
    enforces that the name resolves to a registered flow adapter at
    launcher time.
    """

    backend: Annotated[Literal["custom"], Profile.USER] = Field(
        default="custom",
        description="Discriminator tag indicating a plugin-provided flow backend.",
    )
    name: Annotated[str, Profile.USER] = Field(
        ...,
        description="Plugin-registered flow backend name (matches registry).",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> str:
        cleaned = str(getattr(value, "value", value)).strip().lower()
        if cleaned == "":
            raise ValueError("solver.backend.name cannot be empty.")
        return cleaned


SolverBackendConfig: TypeAlias = Annotated[
    Modflow6Backend | ModflowNwtBackend | BoussinesqBackend | CustomBackend,
    Field(
        discriminator="backend",
        description=("Discriminated union of flow solver backends tagged by the 'backend' key."),
    ),
]


class SolverConfig(HydroModelBase):
    """Configuration block defining the active groundwater solver engine.

    The V1 TOML form is ``backend = { backend = "modflow6" }`` for a
    built-in backend, or ``backend = { backend = "custom", name = "x" }``
    for a plugin-registered backend.

    It also carries the backend-agnostic preprocessing switches both MODFLOW
    backends read, so one TOML key drives both. ``sink_fill`` and
    ``drain_band_depth_m`` both act on the drains of a depressed model top and
    are mutually exclusive.
    """

    backend: Annotated[SolverBackendConfig, Profile.USER] = Field(
        default_factory=Modflow6Backend,
        description="Active flow backend selector (discriminated union).",
    )
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
            "connects, not on the eight neighbours a raster fill uses: measured "
            "on the Nancon, 4.56 per cent of the mesh against 2.12 per cent, a "
            "factor of two that is the neighbourhood and nothing else. NOT "
            "SANCTIONED BY ANY SOURCE: no manual, no USGS document and no "
            "guideline removes a discharge boundary where a pit is detected, and "
            "measured here it degrades both scores. The remedy the USGS does "
            "document for the same question is solver.drain_band_depth_m, which "
            "gives every cell a discharge band instead of taking the drain away. "
            "Default false, which drains every cell as before."
        ),
        examples=[False, True],
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

    @property
    def backend_name(self) -> str:
        """Canonical backend name compatible with the solver registry."""
        if isinstance(self.backend, CustomBackend):
            return self.backend.name
        return self.backend.backend

    def validate_registry(self) -> None:
        """Verify the selected engine is registered. Call explicitly from launcher."""
        from hydromodpy.solver.base import registry

        registry.load_plugins()
        engine = self.backend_name
        if not registry.is_supported("flow", engine):
            known = ", ".join(name for _, name in registry.pairs_for_process("flow"))
            raise ValueError(f"Unknown flow solver '{engine}'. Registered flow solvers: {known}.")
