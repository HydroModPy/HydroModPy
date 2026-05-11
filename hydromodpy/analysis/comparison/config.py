"""Runtime configuration models for the in-process comparison pipeline.

This module owns the internal, post-resolution view of a comparison: the
`Runtime*` schemas consumed directly by the analytical layer
(`runtime.py`, `runtime_config.py`, `runtime_observables.py`, `visuals.py`,
`visuals_payloads.py`). `RuntimeComparisonConfig.from_toml` accepts the
public simulation-comparison TOML, flattens the optional `[execution]` block,
drops the experiment-only `[audit]` section, and resolves every path against
`config_path.parent`. The result is the canonical input fed into the
in-process comparison runtime.

The sibling module `experiment_config.py` owns a different concern: the
verbose, user-facing experiment contract used by `experiment_launcher.py`
to spawn child simulations as subprocesses, with its own `[execution]` and
`[audit]` sub-configs and a stricter, enabled-only id-resolution policy.
The launcher first builds a `SimulationComparisonConfig` from that contract,
then constructs a `RuntimeComparisonConfig` here to drive the runtime.

Both files share the leaf models `ComparisonObservable` and
`ComparisonFineRaster`, both defined here and re-imported by
`experiment_config.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    IdentifierStr,
    NonEmptyStr,
    NonNegativeInt,
    OptionalText,
    PositiveFloat,
)
from hydromodpy.core.config_kit.validators import validate_optional_identifier
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


class ComparisonSimulation(HydroModelBase):
    """One simulation to run or reuse in a comparison."""

    id: Annotated[IdentifierStr, Profile.USER] = Field(
        description="Unique identifier of this simulation entry inside the comparison."
    )
    label: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Optional human-readable label used in plots and reports.",
    )
    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Whether this simulation participates in the comparison run.",
    )
    simulation_config: Annotated[OptionalText, Profile.EXPERT] = Field(
        default=None,
        description="Path to a standalone simulation TOML config, resolved against the base dir.",
    )
    run_folder: Annotated[OptionalText, Profile.EXPERT] = Field(
        default=None,
        description="Path to an existing run output folder reused instead of executing the solver.",
    )
    solver: Annotated[OptionalText, Profile.EXPERT] = Field(
        default=None,
        description="Solver key (e.g. modflow6, modflow_nwt) when generating from the base config.",
    )
    mesh_label: Annotated[IdentifierStr | None, Profile.USER] = Field(
        default=None,
        description="Optional mesh identifier used to align this simulation with a known mesh.",
    )
    mesh_mode: Annotated[
        Literal[
            "mesh_catchment",
            "mesh_input",
            "sgrid",
            "structured",
            "unstructured",
            "unknown",
        ],
        Profile.DEV,
    ] = Field(
        default="unknown",
        description="Mesh kind tag used to drive backend-specific post-processing.",
    )
    overlay: Annotated[dict[str, Any], Profile.EXPERT] = Field(
        default_factory=dict,
        description=(
            "Child-specific TOML overlay merged after the shared base simulation "
            "payload. Use it for solver- or method-specific changes; site-wide "
            "inputs shared by all methods belong in comparison.base_simulation_overlay."
        ),
    )

    _normalize_mesh_label = field_validator("mesh_label")(validate_optional_identifier)

    @field_validator("overlay")
    @classmethod
    def _validate_overlay(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("comparison.simulation.overlay must be a mapping")
        return dict(value)


class ComparisonObservable(HydroModelBase):
    """One quantity of interest extracted from each simulation run folder."""

    name: Annotated[IdentifierStr, Profile.USER] = Field(
        description="Unique identifier of this observable inside the comparison."
    )
    variable: Annotated[NonEmptyStr, Profile.USER] = Field(
        description="Name of the simulated variable to extract (e.g. head, discharge)."
    )
    source: Annotated[Literal["disk"], Profile.USER] = Field(
        default="disk",
        description="Backing store for the extracted values; currently only disk outputs.",
    )
    simulations: Annotated[list[IdentifierStr] | None, Profile.USER] = Field(
        default=None,
        description="Subset of simulation ids this observable applies to; null means all.",
    )
    support: Annotated[Literal["point", "outlet", "boundary", "cell_mask", "map"], Profile.USER] = (
        Field(
            default="point",
            description="Spatial support of the observable (point, outlet, boundary, mask, map).",
        )
    )
    anchor_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Optional anchor key resolved from anchors_file to provide x and y.",
    )
    x: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Easting in meters (EPSG:2154 / Lambert 93).",
    )
    y: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="Northing in meters (EPSG:2154 / Lambert 93).",
    )
    cell_index: Annotated[NonNegativeInt | None, Profile.USER] = Field(
        default=None,
        description="Zero-based mesh cell index for point or outlet support.",
    )
    cell_indices: Annotated[list[NonNegativeInt] | None, Profile.USER] = Field(
        default=None,
        min_length=1,
        description="List of zero-based mesh cell indices used for cell_mask support.",
    )
    boundary_id: Annotated[IdentifierStr | None, Profile.USER] = Field(
        default=None,
        description="Identifier of the boundary group selected for boundary support.",
    )
    allow_domain_proxy: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Allow whole-domain reduction as outlet fallback when no location is set.",
    )
    time: Annotated[str | int | None, Profile.USER] = Field(
        default="all",
        description="Timestep selector (timestamp, integer index, or 'all').",
    )
    time_window: Annotated[tuple[str, str] | tuple[float, float] | None, Profile.USER] = Field(
        default=None,
        description="Optional inclusive time window as a (start, end) pair, mutually exclusive with time.",
    )
    reducer: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Spatial reducer applied over the support (e.g. nearest_cell, sum, max).",
    )
    time_reducer: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Temporal reducer applied over the selected timesteps (e.g. mean, sum).",
    )
    unit: Annotated[OptionalText, Profile.USER] = Field(
        default=None,
        description="Optional unit label attached to the extracted values for display.",
    )

    _normalize_anchor_boundary_ids = field_validator("anchor_id", "boundary_id")(
        validate_optional_identifier
    )

    @field_validator("simulations")
    @classmethod
    def _validate_simulations(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("comparison.observable.simulations must be a non-empty list")
        cleaned = []
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("comparison.observable.simulations cannot contain empty ids")
            cleaned.append(text)
        return cleaned

    @model_validator(mode="before")
    @classmethod
    def _default_reducer(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_reducer = payload.get("reducer")
        if raw_reducer is not None and str(raw_reducer).strip():
            return payload
        support = str(payload.get("support", "point")).strip()
        if support == "point":
            payload["reducer"] = "nearest_cell"
        elif support == "outlet":
            variable_key = str(payload.get("variable", "")).strip().lower()
            payload["reducer"] = "max" if "accumulation" in variable_key else "sum"
        elif support in {"boundary", "cell_mask"}:
            payload["reducer"] = "sum"
        elif support == "map":
            payload["reducer"] = "identity"
        return payload

    @model_validator(mode="after")
    def _validate_support_specific_fields(self) -> ComparisonObservable:
        if self.time is not None and self.time_window is not None:
            raise ValueError("comparison.observable cannot declare both time and time_window")
        if self.support == "point":
            has_coordinates = self.x is not None and self.y is not None
            has_anchor = self.anchor_id is not None
            if not has_coordinates and not has_anchor and self.cell_index is None:
                raise ValueError(
                    "point observables require x/y coordinates, anchor_id, or cell_index"
                )
        elif self.support == "outlet":
            has_coordinates = self.x is not None and self.y is not None
            has_anchor = self.anchor_id is not None
            if (
                self.cell_index is None
                and not has_coordinates
                and not has_anchor
                and not self.allow_domain_proxy
            ):
                raise ValueError(
                    "outlet observables require cell_index, x/y coordinates, or anchor_id. "
                    "Set allow_domain_proxy=true only for exploratory whole-domain "
                    "reducer comparisons."
                )
        elif self.support == "boundary":
            if self.boundary_id is None and not self.cell_indices:
                raise ValueError("boundary observables require boundary_id or cell_indices")
        return self


class RuntimeComparisonSection(HydroModelBase):
    """Launcher-owned comparison section."""

    comparison_id: Annotated[IdentifierStr | None, Profile.USER] = Field(
        default=None,
        description="Identifier of the comparison; defaults to the TOML config stem when omitted.",
    )
    base_simulation_config: Annotated[OptionalText, Profile.EXPERT] = Field(
        default=None,
        description="Path to a shared base simulation TOML used to generate child configs.",
    )
    base_simulation_overlay: Annotated[dict[str, Any], Profile.EXPERT] = Field(
        default_factory=dict,
        description=(
            "Shared TOML overlay applied to the base simulation config before each "
            "child-specific comparison.simulation.overlay. It carries the physical "
            "case definition common to all compared simulations, especially in "
            "catalog-driven testbeds."
        ),
    )
    anchors_file: Annotated[OptionalText, Profile.EXPERT] = Field(
        default=None,
        description="Path to a TOML file declaring named (x, y) anchors in EPSG:2154 meters.",
    )
    output_root: Annotated[OptionalText, Profile.EXPERT] = Field(
        default=None,
        description="Override for the comparison output root; defaults to base_dir/comparison/<id>.",
    )
    run_simulations: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Whether to actually execute simulations; if false, only reuse existing outputs.",
    )
    continue_on_error: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Continue the comparison when an individual simulation fails.",
    )
    reference_simulation: Annotated[IdentifierStr | None, Profile.EXPERT] = Field(
        default=None,
        description="Id of the simulation used as the reference for relative metrics and grids.",
    )
    fine_raster: Annotated[ComparisonFineRaster | None, Profile.EXPERT] = Field(
        default=None,
        description="Optional shared rasterization settings used to compare map outputs.",
    )
    simulation: Annotated[list[ComparisonSimulation], Profile.USER] = Field(
        default_factory=list,
        description="Simulations to run or reuse in the comparison. At least one entry required.",
    )
    observable: Annotated[list[ComparisonObservable], Profile.USER] = Field(
        default_factory=list,
        description="Observables to compare across the declared simulations. At least one entry required.",
    )

    _normalize_comparison_identifiers = field_validator("comparison_id", "reference_simulation")(
        validate_optional_identifier
    )

    @field_validator("base_simulation_overlay")
    @classmethod
    def _validate_base_simulation_overlay(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("comparison.base_simulation_overlay must be a mapping")
        return dict(value)

    @model_validator(mode="after")
    def _validate_non_empty_lists(self) -> RuntimeComparisonSection:
        if not self.simulation:
            raise ValueError("comparison.simulation must contain at least one item")
        if not self.observable:
            raise ValueError("comparison.observable must contain at least one item")
        ids = [simulation.id for simulation in self.simulation]
        if len(set(ids)) != len(ids):
            raise ValueError("comparison.simulation ids must be unique")
        observable_names = [observable.name for observable in self.observable]
        if len(set(observable_names)) != len(observable_names):
            raise ValueError("comparison.observable names must be unique")
        if self.reference_simulation is not None and self.reference_simulation not in set(ids):
            raise ValueError("comparison.reference_simulation must match a declared simulation id")
        simulation_ids = set(ids)
        for observable in self.observable:
            if observable.simulations is None:
                continue
            missing = sorted(set(observable.simulations) - simulation_ids)
            if missing:
                missing_text = ", ".join(missing)
                raise ValueError(
                    f"comparison.observable.simulations contains unknown ids: {missing_text}"
                )
        return self


class ComparisonFineRaster(HydroModelBase):
    """Optional common regular-grid rasterization for map comparisons."""

    enabled: Annotated[bool, Profile.EXPERT] = Field(
        default=False,
        description="Enable the shared fine raster for map comparisons.",
    )
    resolution: Annotated[PositiveFloat | None, Profile.EXPERT] = Field(
        default=None,
        description="Target raster cell size in meters (EPSG:2154 grid).",
    )
    extent_mode: Annotated[Literal["intersection", "union", "reference"], Profile.EXPERT] = Field(
        default="intersection",
        description="Strategy used to derive the common raster extent across simulations.",
    )
    interpolation: Annotated[Literal["linear", "nearest"], Profile.EXPERT] = Field(
        default="linear",
        description="Regridding method used to project each map onto the shared fine raster.",
    )
    write_geotiff: Annotated[bool, Profile.EXPERT] = Field(
        default=True,
        description="Write the regridded maps as GeoTIFF files alongside the comparison figures.",
    )

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> ComparisonFineRaster:
        if self.enabled and self.resolution is None:
            raise ValueError(
                "comparison.fine_raster.resolution is required when fine_raster.enabled=true"
            )
        return self


class RuntimeComparisonConfig(HydroModelBase):
    """Validated top-level configuration for TOML-compatible comparisons."""

    config_path: Annotated[Path, Profile.EXPERT]
    base_dir: Annotated[Path, Profile.EXPERT]
    comparison_root: Annotated[Path, Profile.EXPERT]
    base_simulation_config_path: Annotated[Path | None, Profile.EXPERT] = None
    anchors_path: Annotated[Path | None, Profile.EXPERT] = None
    anchors: Annotated[dict[str, tuple[float, float]], Profile.EXPERT] = Field(
        default_factory=dict,
        description="Anchor points loaded from anchors_file, keyed by anchor id, as (x, y) pairs.",
    )
    comparison: Annotated[RuntimeComparisonSection, Profile.USER]

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> RuntimeComparisonConfig:
        """Validate one raw TOML payload and resolve launcher-owned paths."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        if "comparison" not in raw_toml:
            raise KeyError("Missing required section 'comparison'")
        section_payload = _as_internal_comparison_payload(raw_toml["comparison"])

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        section = RuntimeComparisonSection.model_validate(section_payload)

        comparison_id = section.comparison_id or resolved_config_path.stem
        section.comparison_id = comparison_id

        if section.output_root is None:
            comparison_root = base_dir / "comparison" / comparison_id
        else:
            comparison_root = Path(section.output_root).expanduser()
            if not comparison_root.is_absolute():
                comparison_root = base_dir / comparison_root
        comparison_root = comparison_root.resolve()

        base_simulation_config_path: Path | None = None
        if section.base_simulation_config is not None:
            base_simulation_config_path = Path(section.base_simulation_config).expanduser()
            if not base_simulation_config_path.is_absolute():
                base_simulation_config_path = base_dir / base_simulation_config_path
            base_simulation_config_path = base_simulation_config_path.resolve()

        anchors_path: Path | None = None
        anchors: dict[str, tuple[float, float]] = {}
        if section.anchors_file is not None:
            anchors_path = Path(section.anchors_file).expanduser()
            if not anchors_path.is_absolute():
                anchors_path = base_dir / anchors_path
            anchors_path = anchors_path.resolve()
            anchors = _load_comparison_anchors(anchors_path)
            _apply_observable_anchors(section.observable, anchors)
        elif any(observable.anchor_id is not None for observable in section.observable):
            raise ValueError("comparison.observable.anchor_id requires comparison.anchors_file")

        cfg = cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            comparison_root=comparison_root,
            base_simulation_config_path=base_simulation_config_path,
            anchors_path=anchors_path,
            anchors=anchors,
            comparison=section,
        )
        cfg._validate_simulation_inputs()
        return cfg

    def _validate_simulation_inputs(self) -> None:
        """Validate path modes requiring top-level base-config context."""
        for simulation in self.comparison.simulation:
            if not simulation.enabled:
                continue
            has_direct_config = simulation.simulation_config is not None
            has_generated_config = self.base_simulation_config_path is not None and bool(
                simulation.overlay or simulation.solver
            )
            has_run_folder = simulation.run_folder is not None
            if not (has_direct_config or has_generated_config or has_run_folder):
                raise ValueError(
                    "Each enabled comparison.simulation requires "
                    "simulation_config, run_folder, or base_simulation_config "
                    "with overlay/solver"
                )

    def resolve_simulation_config_path(
        self,
        simulation: ComparisonSimulation,
    ) -> Path | None:
        """Resolve a simulation's declared config path, if any."""
        if simulation.simulation_config is None:
            return None
        path = Path(simulation.simulation_config).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    def resolve_simulation_run_folder(
        self,
        simulation: ComparisonSimulation,
    ) -> Path | None:
        """Resolve a simulation's declared existing run folder, if any."""
        if simulation.run_folder is None:
            return None
        path = Path(simulation.run_folder).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()


__all__ = (
    "RuntimeComparisonConfig",
    "ComparisonFineRaster",
    "ComparisonObservable",
    "RuntimeComparisonSection",
    "ComparisonSimulation",
)


def _load_comparison_anchors(path: Path) -> dict[str, tuple[float, float]]:
    """Load flattened XY anchors from one TOML file."""
    raw_toml = load_toml_with_base_config(path)
    raw_anchors = raw_toml.get("comparison_anchors")
    if not isinstance(raw_anchors, Mapping):
        raise KeyError(f"Anchors file '{path}' must expose a [comparison_anchors] tree")
    anchors: dict[str, tuple[float, float]] = {}
    _collect_anchor_nodes(raw_anchors, anchors=anchors, prefix=())
    if not anchors:
        raise ValueError(f"Anchors file '{path}' does not define any x/y anchor")
    return anchors


def _collect_anchor_nodes(
    mapping: Mapping[str, Any],
    *,
    anchors: dict[str, tuple[float, float]],
    prefix: tuple[str, ...],
) -> None:
    if "x" in mapping and "y" in mapping:
        if not prefix:
            raise ValueError("Anchor nodes must be nested under a non-empty id path")
        anchors[".".join(prefix)] = (float(mapping["x"]), float(mapping["y"]))
    for key, value in mapping.items():
        if key in {"x", "y"}:
            continue
        if isinstance(value, Mapping):
            _collect_anchor_nodes(value, anchors=anchors, prefix=(*prefix, str(key)))


def _apply_observable_anchors(
    observables: list[ComparisonObservable],
    anchors: Mapping[str, tuple[float, float]],
) -> None:
    for observable in observables:
        anchor_id = observable.anchor_id
        if anchor_id is None or (observable.x is not None and observable.y is not None):
            continue
        if anchor_id not in anchors:
            raise KeyError(f"Unknown comparison anchor_id '{anchor_id}'")
        observable.x, observable.y = anchors[anchor_id]


def _as_internal_comparison_payload(section_payload: Any) -> Any:
    """Map public simulation-comparison TOML to the internal comparison model."""
    if not isinstance(section_payload, Mapping):
        return section_payload
    normalized = dict(section_payload)

    execution = normalized.pop("execution", None)
    if isinstance(execution, Mapping) and "run_simulations" in execution:
        normalized["run_simulations"] = bool(execution["run_simulations"])

    normalized.pop("audit", None)
    return normalized
