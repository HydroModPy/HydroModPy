"""External experiment contract for subprocess-driven comparison launchers.

This module owns the verbose, user-facing TOML schema consumed by
`experiment_launcher.py` to orchestrate a comparison as a set of child
simulations executed in subprocesses (currently `subprocess_hmp_run`).
It exposes:

- `ComparisonExecutionConfig` and `ComparisonAuditConfig`: experiment-only
  sub-sections describing how children are launched and how their cases
  are audited post-run.
- `ComparisonSimulationConfig` and `ComparisonSection`: the experiment-side
  twins of `ComparisonSimulation` / `RuntimeComparisonSection` from
  `config.py`. They differ from the runtime models on purpose: the
  experiment requires a `solver` (or a direct config/run folder) at parse
  time, exposes `execution` and `audit`, and validates id references
  against the enabled subset only.
- `SimulationComparisonConfig`: the resolved external config with absolute
  paths, built by `from_toml` and used as launcher input. The launcher
  later derives a `RuntimeComparisonConfig` from it to feed the in-process
  runtime defined in `config.py`.

The sibling module `config.py` owns the runtime-side contract used after
resolution by `runtime.py` and the visual layer. The shared leaf models
`ComparisonObservable` and `ComparisonFineRaster` live in `config.py` and
are re-imported here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.analysis.comparison.config import (
    ComparisonFineRaster,
    ComparisonObservable,
    _normalize_optional_mesh_label,
    _apply_observable_anchors,
    _load_comparison_anchors,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IdentifierStr, OptionalText
from hydromodpy.core.config_kit.validators import validate_optional_identifier


class ComparisonExecutionConfig(HydroModelBase):
    """How comparison child simulations are executed."""

    backend: Annotated[Literal["subprocess_hmp_run"], Profile.DEV] = "subprocess_hmp_run"
    max_parallel_runs: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description="Number of child simulations executed in parallel. Forced to 1 in V1.",
    )
    keep_generated_configs: Annotated[bool, Profile.DEV] = True
    run_simulations: Annotated[bool, Profile.DEV] = True
    python_executable: Annotated[OptionalText, Profile.DEV] = None
    timeout_seconds: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=0,
        description="Optional per-child timeout in seconds. None disables the timeout.",
    )

    @model_validator(mode="after")
    def _validate_v1_scope(self) -> ComparisonExecutionConfig:
        if self.max_parallel_runs != 1:
            raise ValueError("comparison.execution.max_parallel_runs must be 1 in V1")
        return self


class ComparisonAuditConfig(HydroModelBase):
    """Post-run equivalence policy for child simulations."""

    mode: Annotated[Literal["strict_same_case"], Profile.DEV] = "strict_same_case"
    on_mismatch: Annotated[Literal["fail", "warn", "ignore"], Profile.DEV] = "fail"


class ComparisonSimulationConfig(HydroModelBase):
    """One generated child simulation in a comparison experiment."""

    id: Annotated[IdentifierStr, Profile.USER]
    label: Annotated[OptionalText, Profile.USER] = None
    enabled: Annotated[bool, Profile.USER] = True
    solver: Annotated[OptionalText, Profile.EXPERT] = None
    simulation_config: Annotated[OptionalText, Profile.EXPERT] = None
    run_folder: Annotated[OptionalText, Profile.EXPERT] = None
    mesh_label: Annotated[IdentifierStr | None, Profile.USER] = None
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

    _normalize_mesh_label = field_validator("mesh_label", mode="before")(
        _normalize_optional_mesh_label
    )

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

    comparison_id: Annotated[IdentifierStr | None, Profile.USER] = Field(
        default=None,
        description="Stable identifier for this comparison run.",
    )
    base_simulation_config: Annotated[OptionalText, Profile.EXPERT] = None
    base_simulation_overlay: Annotated[dict[str, Any], Profile.EXPERT] = Field(
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
    anchors_file: Annotated[OptionalText, Profile.EXPERT] = None
    output_root: Annotated[OptionalText, Profile.EXPERT] = None
    reference_simulation: Annotated[IdentifierStr | None, Profile.EXPERT] = None
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
