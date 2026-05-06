"""Configuration contract for external simulation-comparison experiments."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.analysis.comparison.config import (
    ComparisonFineRaster,
    ComparisonObservable,
    _apply_observable_anchors,
    _load_comparison_anchors,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


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

    backend: Annotated[Literal["subprocess_hmp_run"], Profile.DEV] = "subprocess_hmp_run"
    max_parallel_runs: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Number of child simulations executed in parallel. Forced to 1 in V1.",
    )
    keep_generated_configs: Annotated[bool, Profile.DEV] = True
    run_simulations: Annotated[bool, Profile.DEV] = True
    python_executable: Annotated[str | None, Profile.DEV] = None
    timeout_seconds: Annotated[float | None, Profile.DEV] = Field(
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

    mode: Annotated[Literal["strict_same_case"], Profile.DEV] = "strict_same_case"
    on_mismatch: Annotated[Literal["fail", "warn", "ignore"], Profile.DEV] = "fail"


class ComparisonSimulationConfig(HydroModelBase):
    """One generated child simulation in a comparison experiment."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Profile.USER]
    label: Annotated[str | None, Profile.USER] = None
    enabled: Annotated[bool, Profile.USER] = True
    solver: Annotated[str | None, Profile.EXPERT] = None
    simulation_config: Annotated[str | None, Profile.EXPERT] = None
    run_folder: Annotated[str | None, Profile.EXPERT] = None
    mesh_label: Annotated[str | None, Profile.USER] = None
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
    ] = "unknown"
    overlay: Annotated[dict[str, Any], Profile.EXPERT] = Field(
        default_factory=dict,
        description="Free-form TOML overlay merged into the base simulation config when this child runs.",
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

    comparison_id: Annotated[str | None, Profile.USER] = None
    base_simulation_config: Annotated[str | None, Profile.EXPERT] = None
    anchors_file: Annotated[str | None, Profile.EXPERT] = None
    output_root: Annotated[str | None, Profile.EXPERT] = None
    reference_simulation: Annotated[str | None, Profile.EXPERT] = None
    continue_on_error: Annotated[bool, Profile.DEV] = False
    execution: Annotated[ComparisonExecutionConfig, Profile.DEV] = Field(
        default_factory=ComparisonExecutionConfig,
        description="Execution settings for the comparison child runs.",
    )
    audit: Annotated[ComparisonAuditConfig, Profile.DEV] = Field(
        default_factory=ComparisonAuditConfig,
        description="Post-run audit policy applied to each child simulation.",
    )
    fine_raster: Annotated[ComparisonFineRaster | None, Profile.EXPERT] = None
    simulation: Annotated[list[ComparisonSimulationConfig], Profile.USER] = Field(
        default_factory=list,
        description="Generated child simulations to run in the comparison. At least one entry required.",
    )
    observable: Annotated[list[ComparisonObservable], Profile.USER] = Field(
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

    config_path: Annotated[Path, Profile.EXPERT]
    base_dir: Annotated[Path, Profile.EXPERT]
    comparison_root: Annotated[Path, Profile.EXPERT]
    base_simulation_config_path: Annotated[Path | None, Profile.EXPERT] = None
    anchors_path: Annotated[Path | None, Profile.EXPERT] = None
    anchors: Annotated[dict[str, tuple[float, float]], Profile.EXPERT] = Field(
        default_factory=dict,
        description="Anchor points loaded from anchors_file, keyed by anchor id, as (x, y) pairs.",
    )
    comparison: Annotated[ComparisonSection, Profile.USER]

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
