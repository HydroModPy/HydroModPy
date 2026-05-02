"""Configuration contract for external simulation-comparison experiments."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.analysis.comparison.config import (
    MethodComparisonFineRaster,
    MethodComparisonObservable,
)
from hydromodpy.core.config.base import HydroModelBase


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

    backend: Literal["subprocess_hmp_run"] = "subprocess_hmp_run"
    max_parallel_runs: int = Field(default=1, ge=1)
    keep_generated_configs: bool = True
    run_simulations: bool = True
    python_executable: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)

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

    mode: Literal["strict_same_case"] = "strict_same_case"
    on_mismatch: Literal["fail", "warn", "ignore"] = "fail"


class ComparisonSimulationConfig(HydroModelBase):
    """One generated child simulation in a comparison experiment."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    enabled: bool = True
    solver: str
    mesh_label: str | None = None
    mesh_mode: Literal[
        "mesh_catchment",
        "mesh_input",
        "sgrid",
        "structured",
        "unstructured",
        "unknown",
    ] = "unknown"
    overlay: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: object) -> str:
        return _clean_path_safe_id(value, field_name="comparison.simulation.id")

    @field_validator("solver")
    @classmethod
    def _validate_solver_text(cls, value: object) -> str:
        return _clean_text(value)

    @field_validator("label", "mesh_label")
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
        if not self.solver:
            raise ValueError("comparison.simulation.solver is required")
        return self


class ComparisonSection(HydroModelBase):
    """Top-level comparison experiment section."""

    model_config = ConfigDict(extra="forbid")

    comparison_id: str | None = None
    base_simulation_config: str
    output_root: str | None = None
    reference_simulation: str | None = None
    continue_on_error: bool = False
    execution: ComparisonExecutionConfig = Field(default_factory=ComparisonExecutionConfig)
    audit: ComparisonAuditConfig = Field(default_factory=ComparisonAuditConfig)
    fine_raster: MethodComparisonFineRaster | None = None
    simulation: list[ComparisonSimulationConfig] = Field(default_factory=list)
    observable: list[MethodComparisonObservable] = Field(default_factory=list)

    @field_validator(
        "base_simulation_config",
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
        if not self.base_simulation_config:
            raise ValueError("comparison.base_simulation_config is required")
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
        if self.reference_simulation is not None and self.reference_simulation not in enabled_id_set:
            raise ValueError("comparison.reference_simulation must match an enabled simulation id")
        for observable in self.observable:
            if observable.variants is None:
                continue
            missing = sorted(set(observable.variants) - enabled_id_set)
            if missing:
                missing_text = ", ".join(missing)
                raise ValueError(
                    f"comparison.observable.variants contains unknown or disabled ids: {missing_text}"
                )
        return self


class SimulationComparisonConfig(HydroModelBase):
    """Resolved comparison experiment config with absolute paths."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_path: Path
    base_dir: Path
    comparison_root: Path
    base_simulation_config_path: Path
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

        base_simulation_config = Path(section.base_simulation_config).expanduser()
        if not base_simulation_config.is_absolute():
            base_simulation_config = base_dir / base_simulation_config
        base_simulation_config = base_simulation_config.resolve()
        if not base_simulation_config.is_file():
            raise FileNotFoundError(
                f"comparison.base_simulation_config not found: {base_simulation_config}"
            )

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
            comparison=section,
        )


__all__ = (
    "ComparisonAuditConfig",
    "ComparisonExecutionConfig",
    "ComparisonSection",
    "ComparisonSimulationConfig",
    "SimulationComparisonConfig",
)
