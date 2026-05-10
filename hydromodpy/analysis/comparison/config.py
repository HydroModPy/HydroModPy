"""Internal configuration models for simulation-comparison workflows."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def _clean_optional_text(value: object) -> str | None:
    """Normalize optional user text fields."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class ComparisonSimulation(HydroModelBase):
    """One simulation to run or reuse in a comparison."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description=(
            "Stable child simulation identifier inside this comparison. It is used in "
            "generated file names, run names, metrics, figure labels, and observable "
            "rows."
        )
    )
    label: str | None = Field(
        default=None,
        description="Human-readable label for plots and HTML tables.",
    )
    enabled: bool = Field(
        default=True,
        description="If False, keep this child declaration but skip it during execution.",
    )
    simulation_config: str | None = Field(
        default=None,
        description="Path to an already existing simulation TOML to compare.",
    )
    run_folder: str | None = Field(
        default=None,
        description="Path to an already existing simulation run folder to compare.",
    )
    solver: str | None = Field(
        default=None,
        description="Solver name used when a child config is generated from the base simulation.",
    )
    mesh_label: str | None = Field(
        default=None,
        description="Short label describing the mesh provenance for this child.",
    )
    mesh_mode: Literal[
        "mesh_catchment",
        "mesh_input",
        "sgrid",
        "structured",
        "unstructured",
        "unknown",
    ] = Field(
        default="unknown",
        description="Mesh provenance category used for reporting and audit context.",
    )
    overlay: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Child-specific TOML overlay merged after the shared base simulation "
            "payload. Use it for solver- or method-specific changes; site-wide "
            "inputs shared by all methods belong in comparison.base_simulation_overlay."
        ),
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("comparison.simulation.id cannot be empty")
        if any(token in text for token in ("/", "\\")):
            raise ValueError("comparison.simulation.id cannot contain path separators")
        return text

    @field_validator(
        "label",
        "simulation_config",
        "run_folder",
        "solver",
        "mesh_label",
    )
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

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

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "Stable observable identifier. It becomes the group name used in metrics, "
            "differences, figures, and HTML sections."
        )
    )
    variable: str = Field(
        description=(
            "Result variable to extract from each simulation, for example "
            "'watertable_elevation', 'head', 'accumulation_flux', or a comparison "
            "derived variable."
        )
    )
    source: Literal["disk"] = Field(
        default="disk",
        description=(
            "Observable source backend. The current comparison workflow reads persisted "
            "simulation results from disk."
        ),
    )
    simulations: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of simulation ids for this observable. None means all "
            "enabled simulations in the comparison."
        ),
    )
    support: Literal["point", "outlet", "boundary", "cell_mask", "map"] = Field(
        default="point",
        description=(
            "Spatial support used to sample the variable: point nearest-cell series, "
            "outlet aggregate, boundary aggregate, cell-mask aggregate, or full map."
        ),
    )
    anchor_id: str | None = Field(
        default=None,
        description="Named XY anchor loaded from comparison.anchors_file.",
    )
    x: float | None = Field(
        default=None,
        description="X coordinate in the model/project CRS for point or outlet sampling.",
    )
    y: float | None = Field(
        default=None,
        description="Y coordinate in the model/project CRS for point or outlet sampling.",
    )
    cell_index: int | None = Field(
        default=None,
        description="Zero-based cell index used when the observable is tied to one cell.",
    )
    cell_indices: list[int] | None = Field(
        default=None,
        description="Zero-based cell indices used for boundary or cell-mask aggregations.",
    )
    boundary_id: str | None = Field(
        default=None,
        description="Boundary identifier used when support='boundary'.",
    )
    allow_domain_proxy: bool = Field(
        default=False,
        description=(
            "If True, allow a whole-domain proxy when an exact outlet location cannot "
            "be selected. This should remain explicit because it changes the physical "
            "meaning of the observable."
        ),
    )
    time: str | int | None = Field(
        default="all",
        description=(
            "Time selector: 'all', 'first', 'first_computed', 'last', or a zero-based "
            "time index."
        ),
    )
    time_window: tuple[str, str] | tuple[float, float] | None = Field(
        default=None,
        description="Optional time window used instead of a single time selector.",
    )
    reducer: str | None = Field(
        default=None,
        description=(
            "Spatial reducer. Defaults depend on support: nearest-cell for points, "
            "sum for outlets/boundaries, and identity for maps."
        ),
    )
    time_reducer: str | None = Field(
        default=None,
        description="Optional reducer applied across the selected time dimension.",
    )
    unit: str | None = Field(
        default=None,
        description="Display and reporting unit for this observable.",
    )

    @field_validator("name", "variable")
    @classmethod
    def _validate_required_text(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("comparison.observable value cannot be empty")
        return text

    @field_validator("anchor_id", "boundary_id", "reducer", "time_reducer", "unit")
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    @field_validator("cell_index")
    @classmethod
    def _validate_cell_index(cls, value: object) -> int | None:
        if value is None:
            return None
        index = int(value)
        if index < 0:
            raise ValueError("comparison.observable.cell_index must be >= 0")
        return index

    @field_validator("cell_indices")
    @classmethod
    def _validate_cell_indices(cls, value: object) -> list[int] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("comparison.observable.cell_indices must be a non-empty list")
        indices = [int(item) for item in value]
        if any(index < 0 for index in indices):
            raise ValueError("comparison.observable.cell_indices must be >= 0")
        return indices

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
            if self.reducer is None:
                object.__setattr__(self, "reducer", "nearest_cell")
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
            variable_key = self.variable.strip().lower()
            if self.reducer is None:
                object.__setattr__(
                    self, "reducer", "max" if "accumulation" in variable_key else "sum"
                )
        elif self.support == "boundary":
            if self.boundary_id is None and not self.cell_indices:
                raise ValueError("boundary observables require boundary_id or cell_indices")
            if self.reducer is None:
                object.__setattr__(self, "reducer", "sum")
        elif self.support == "cell_mask":
            if self.reducer is None:
                object.__setattr__(self, "reducer", "sum")
        elif self.support == "map":
            if self.reducer is None:
                object.__setattr__(self, "reducer", "identity")
        return self


class ComparisonSection(HydroModelBase):
    """Launcher-owned comparison section."""

    model_config = ConfigDict(extra="forbid")

    comparison_id: str | None = None
    base_simulation_config: str | None = None
    base_simulation_overlay: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Shared TOML overlay applied to the base simulation config before each "
            "child-specific comparison.simulation.overlay. It carries the physical "
            "case definition common to all compared simulations, especially in "
            "catalog-driven testbeds."
        ),
    )
    anchors_file: str | None = None
    output_root: str | None = None
    run_simulations: bool = True
    continue_on_error: bool = False
    reference_simulation: str | None = None
    fine_raster: ComparisonFineRaster | None = None
    simulation: list[ComparisonSimulation] = Field(
        default_factory=list,
        description="Simulations to run or reuse in the comparison. At least one entry required.",
    )
    observable: list[ComparisonObservable] = Field(
        default_factory=list,
        description="Observables to compare across the declared simulations. At least one entry required.",
    )

    @field_validator(
        "comparison_id",
        "base_simulation_config",
        "anchors_file",
        "output_root",
        "reference_simulation",
    )
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    @field_validator("base_simulation_overlay")
    @classmethod
    def _validate_base_simulation_overlay(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("comparison.base_simulation_overlay must be a mapping")
        return dict(value)

    @model_validator(mode="after")
    def _validate_non_empty_lists(self) -> ComparisonSection:
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

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "If True, interpolate map observables onto a common regular raster before "
            "computing map differences and figures."
        ),
    )
    resolution: float | None = Field(
        default=None,
        description="Target raster resolution in project CRS units, usually metres.",
    )
    extent_mode: Literal["intersection", "union", "reference"] = Field(
        default="intersection",
        description=(
            "Common raster extent policy: intersection compares only shared coverage, "
            "union keeps all coverage, and reference follows the reference simulation."
        ),
    )
    interpolation: Literal["linear", "nearest"] = Field(
        default="linear",
        description="Interpolation method used when resampling map observables.",
    )
    write_geotiff: bool = Field(
        default=True,
        description="If True, write GeoTIFF rasters in addition to CSV/PNG outputs.",
    )

    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, value: object) -> float | None:
        if value is None:
            return None
        resolution = float(value)
        if resolution <= 0.0:
            raise ValueError("comparison.fine_raster.resolution must be > 0")
        return resolution

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> ComparisonFineRaster:
        if self.enabled and self.resolution is None:
            raise ValueError(
                "comparison.fine_raster.resolution is required when fine_raster.enabled=true"
            )
        return self


class ComparisonConfig(HydroModelBase):
    """Validated top-level configuration for TOML-compatible comparisons."""

    model_config = ConfigDict(extra="forbid")

    config_path: Path
    base_dir: Path
    comparison_root: Path
    base_simulation_config_path: Path | None = None
    anchors_path: Path | None = None
    anchors: dict[str, tuple[float, float]] = Field(
        default_factory=dict,
        description="Anchor points loaded from anchors_file, keyed by anchor id, as (x, y) pairs.",
    )
    comparison: ComparisonSection

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> ComparisonConfig:
        """Validate one raw TOML payload and resolve launcher-owned paths."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        if "comparison" not in raw_toml:
            raise KeyError("Missing required section 'comparison'")
        section_payload = _as_internal_comparison_payload(raw_toml["comparison"])

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        section = ComparisonSection.model_validate(section_payload)

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
    "ComparisonConfig",
    "ComparisonFineRaster",
    "ComparisonObservable",
    "ComparisonSection",
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
