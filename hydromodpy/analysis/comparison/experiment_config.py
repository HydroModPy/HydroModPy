"""Configuration contract for external simulation-comparison experiments."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.analysis.comparison.config import (
    ComparisonFineRaster,
    ComparisonObservable,
    _apply_observable_anchors,
    _load_comparison_anchors,
)
from hydromodpy.core.config_kit.base import HydroModelBase


def _clean_text(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("comparison text fields cannot be empty")
    return text


def _clean_path_safe_id(value: object, *, field_name: str) -> str:
    text = _clean_text(value)
    if any(token in text for token in ("/", "\\")):
        raise ValueError(f"{field_name} cannot contain path separators")
    return text


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class ComparisonExecutionConfig(HydroModelBase):
    """How comparison child simulations are executed."""

    model_config = ConfigDict(extra="forbid")

    backend: Literal["subprocess_hmp_run"] = Field(
        default="subprocess_hmp_run",
        description=(
            "Execution backend used for generated child simulations. The current "
            "production path launches each generated simulation TOML through the "
            "standard hmp run command, so the comparison workflow does not duplicate "
            "the simulation execution path."
        ),
    )
    max_parallel_runs: int = Field(
        default=1,
        ge=1,
        description="Number of child simulations executed in parallel. Forced to 1 in V1.",
    )
    keep_generated_configs: bool = Field(
        default=True,
        description=(
            "If True, keep the generated child simulation TOMLs under the comparison "
            "output folder. Keeping them is recommended for validation campaigns "
            "because they are the exact configs that were run."
        ),
    )
    run_simulations: bool = Field(
        default=True,
        description=(
            "If True, execute the generated child simulations before extracting "
            "observables. Set False only to reuse already existing run folders or to "
            "dry-check the comparison materialization."
        ),
    )
    python_executable: str | None = Field(
        default=None,
        description=(
            "Optional Python executable used by child subprocesses. None uses the "
            "current interpreter. For PETSc Boussinesq campaigns on Windows hosts, "
            "run the comparison from the WSL environment instead of pointing this "
            "field to a Windows interpreter."
        ),
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description="Optional per-child timeout in seconds. None disables the timeout.",
    )

    @field_validator("python_executable")
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def _validate_v1_scope(self) -> ComparisonExecutionConfig:
        if self.max_parallel_runs != 1:
            raise ValueError("comparison.execution.max_parallel_runs must be 1 in V1")
        return self


class ComparisonAuditConfig(HydroModelBase):
    """Post-run equivalence policy for child simulations."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["strict_same_case"] = Field(
        default="strict_same_case",
        description=(
            "Audit mode applied after all child simulations have produced comparable "
            "observables. The current mode checks that the children describe the same "
            "case before reporting method differences."
        ),
    )
    on_mismatch: Literal["fail", "warn", "ignore"] = Field(
        default="fail",
        description=(
            "Policy applied when the audit detects an incompatible comparison. Use "
            "'fail' for validation gates, 'warn' for exploratory campaigns that should "
            "still write HTML reports, and 'ignore' only when the audit is documented "
            "elsewhere."
        ),
    )


class ComparisonSimulationConfig(HydroModelBase):
    """One generated child simulation in a comparison experiment."""

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
        description=(
            "Human-readable label for plots and HTML tables. When omitted, the child "
            "id is displayed."
        ),
    )
    enabled: bool = Field(
        default=True,
        description=(
            "If False, the child declaration is kept in the config but skipped during "
            "materialization and execution."
        ),
    )
    solver: str | None = Field(
        default=None,
        description=(
            "Solver name used to build the generated simulation process overlay. Use "
            "values such as 'modflow6' or 'boussinesq' when simulation_config and "
            "run_folder are not supplied."
        ),
    )
    simulation_config: str | None = Field(
        default=None,
        description=(
            "Optional path to an already existing simulation TOML. When provided, the "
            "comparison reuses this config instead of generating one from "
            "base_simulation_config."
        ),
    )
    run_folder: str | None = Field(
        default=None,
        description=(
            "Optional path to an existing run folder. Use this for post-processing "
            "comparisons that should not launch or regenerate simulations."
        ),
    )
    mesh_label: str | None = Field(
        default=None,
        description=(
            "Short label describing the mesh used by this child. It is reported in "
            "the comparison manifest and HTML context."
        ),
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
        description=(
            "Mesh provenance category for this child. Use 'mesh_catchment' when the "
            "simulation regenerates an irregular catchment mesh, 'mesh_input' when it "
            "reuses an exchanged mesh bundle, or a structured/unstructured category "
            "when that better describes the solver grid."
        ),
    )
    overlay: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Child-specific TOML overlay merged after comparison.base_simulation_overlay "
            "and after the shared base simulation config. Use it for solver-specific "
            "settings, child labels, child process selection, or deliberately varied "
            "method parameters. Site-wide inputs that must be identical for every "
            "child in one comparison, such as outlet coordinates, recharge forcing, "
            "mesh generation settings, or reference data paths, should be placed in "
            "comparison.base_simulation_overlay instead."
        ),
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: object) -> str:
        return _clean_path_safe_id(value, field_name="comparison.simulation.id")

    @field_validator("solver")
    @classmethod
    def _validate_solver_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return _clean_text(value)

    @field_validator("label", "simulation_config", "run_folder", "mesh_label")
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

    @model_validator(mode="after")
    def _validate_solver(self) -> ComparisonSimulationConfig:
        if not self.solver and not self.simulation_config and not self.run_folder:
            raise ValueError(
                "comparison.simulation.solver is required unless simulation_config "
                "or run_folder is provided"
            )
        return self


class ComparisonSection(HydroModelBase):
    """Top-level comparison experiment section."""

    model_config = ConfigDict(extra="forbid")

    comparison_id: str | None = Field(
        default=None,
        description=(
            "Stable identifier for this comparison run. It is used in generated child "
            "run names, output paths, manifests, and HTML pages."
        ),
    )
    base_simulation_config: str | None = Field(
        default=None,
        description=(
            "Path to the shared simulation TOML used to generate child simulations. "
            "The comparison launcher loads this base once, applies "
            "comparison.base_simulation_overlay, then applies each "
            "comparison.simulation.overlay."
        ),
    )
    base_simulation_overlay: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Shared TOML overlay applied to the base simulation config before any "
            "child-specific comparison.simulation.overlay. This is the preferred hook "
            "for catalog-driven site loops: a testbed can render one comparison per "
            "catalog row and inject the row values here, for example geographic outlet "
            "coordinates, target basin area, recharge chronicle path, geology/K-table "
            "paths, mesh-catchment options, initial-condition policy, or common "
            "workspace/data roots. The overlay is intentionally broad because it "
            "describes the physical case shared by all methods being compared; solver "
            "or method differences remain in each comparison.simulation.overlay."
        ),
    )
    anchors_file: str | None = Field(
        default=None,
        description=(
            "Optional TOML file containing reusable named XY anchors for point or "
            "outlet observables."
        ),
    )
    output_root: str | None = Field(
        default=None,
        description=(
            "Directory where comparison artifacts are written. In catalog-driven "
            "testbeds this is usually rendered from the site id so every site gets "
            "its own comparison folder."
        ),
    )
    reference_simulation: str | None = Field(
        default=None,
        description=(
            "Simulation id used as the reference for metrics and differences. If not "
            "provided, the first completed simulation is used."
        ),
    )
    continue_on_error: bool = Field(
        default=False,
        description=(
            "If True, keep running sibling child simulations after one child fails. "
            "For strict validation campaigns, keep False so failures stop the case."
        ),
    )
    execution: ComparisonExecutionConfig = Field(
        default_factory=ComparisonExecutionConfig,
        description="Execution settings for the comparison child runs.",
    )
    audit: ComparisonAuditConfig = Field(
        default_factory=ComparisonAuditConfig,
        description="Post-run audit policy applied to each child simulation.",
    )
    fine_raster: ComparisonFineRaster | None = Field(
        default=None,
        description=(
            "Optional common regular-grid rasterization used before comparing map "
            "observables. Enable it when compared solvers use different meshes and "
            "need a shared support for map differences and figures."
        ),
    )
    simulation: list[ComparisonSimulationConfig] = Field(
        default_factory=list,
        description="Generated child simulations to run in the comparison. At least one entry required.",
    )
    observable: list[ComparisonObservable] = Field(
        default_factory=list,
        description="Observables to compare across the declared simulations. At least one entry required.",
    )

    @field_validator(
        "base_simulation_config",
        "anchors_file",
        "output_root",
        "reference_simulation",
    )
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    @field_validator("comparison_id")
    @classmethod
    def _validate_comparison_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return _clean_path_safe_id(value, field_name="comparison.comparison_id")

    @field_validator("base_simulation_overlay")
    @classmethod
    def _validate_base_simulation_overlay(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("comparison.base_simulation_overlay must be a mapping")
        return dict(value)

    @model_validator(mode="after")
    def _validate_lists(self) -> ComparisonSection:
        if not self.simulation:
            raise ValueError("comparison.simulation must contain at least one item")
        if not self.observable:
            raise ValueError("comparison.observable must contain at least one item")
        ids = [simulation.id for simulation in self.simulation]
        if len(ids) != len(set(ids)):
            raise ValueError("comparison.simulation ids must be unique")
        enabled_ids = [simulation.id for simulation in self.simulation if simulation.enabled]
        if not enabled_ids:
            raise ValueError("comparison.simulation must contain at least one enabled item")
        observable_names = [observable.name for observable in self.observable]
        if len(observable_names) != len(set(observable_names)):
            raise ValueError("comparison.observable names must be unique")
        enabled_id_set = set(enabled_ids)
        if (
            self.reference_simulation is not None
            and self.reference_simulation not in enabled_id_set
        ):
            raise ValueError("comparison.reference_simulation must match an enabled simulation id")
        for observable in self.observable:
            if observable.simulations is None:
                continue
            missing = sorted(set(observable.simulations) - enabled_id_set)
            if missing:
                missing_text = ", ".join(missing)
                raise ValueError(
                    "comparison.observable.simulations contains unknown or disabled ids: "
                    f"{missing_text}"
                )
        needs_generated_config = any(
            simulation.enabled
            and simulation.simulation_config is None
            and simulation.run_folder is None
            for simulation in self.simulation
        )
        if needs_generated_config and not self.base_simulation_config:
            raise ValueError(
                "comparison.base_simulation_config is required for generated simulations"
            )
        return self


class SimulationComparisonConfig(HydroModelBase):
    """Resolved comparison experiment config with absolute paths."""

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
    ) -> SimulationComparisonConfig:
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        if "comparison" not in raw_toml:
            raise KeyError("Missing required section 'comparison'")

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        section = ComparisonSection.model_validate(raw_toml["comparison"])

        comparison_id = section.comparison_id or resolved_config_path.stem
        section.comparison_id = comparison_id

        base_simulation_config: Path | None = None
        if section.base_simulation_config is not None:
            base_simulation_config = Path(section.base_simulation_config).expanduser()
            if not base_simulation_config.is_absolute():
                base_simulation_config = base_dir / base_simulation_config
            base_simulation_config = base_simulation_config.resolve()
            if not base_simulation_config.is_file():
                raise FileNotFoundError(
                    f"comparison.base_simulation_config not found: {base_simulation_config}"
                )

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

        if section.output_root is None:
            comparison_root = base_dir / "comparison" / comparison_id
        else:
            comparison_root = Path(section.output_root).expanduser()
            if not comparison_root.is_absolute():
                comparison_root = base_dir / comparison_root
        comparison_root = comparison_root.resolve()

        return cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            comparison_root=comparison_root,
            base_simulation_config_path=base_simulation_config,
            anchors_path=anchors_path,
            anchors=anchors,
            comparison=section,
        )


__all__ = (
    "ComparisonAuditConfig",
    "ComparisonExecutionConfig",
    "ComparisonSection",
    "ComparisonSimulationConfig",
    "SimulationComparisonConfig",
)
