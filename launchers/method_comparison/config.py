"""Configuration contract for the method-comparison launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _clean_optional_text(value: object) -> str | None:
    """Normalize optional user text fields."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class MethodComparisonVariantSchema(BaseModel):
    """One solver/mesh method variant to run or reuse."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    enabled: bool = True
    simulation_config: str | None = None
    run_folder: str | None = None
    solver: str | None = None
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
        text = str(value).strip()
        if not text:
            raise ValueError("method_comparison.variant.id cannot be empty")
        if any(token in text for token in ("/", "\\")):
            raise ValueError("method_comparison.variant.id cannot contain path separators")
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
            raise ValueError("method_comparison.variant.overlay must be a mapping")
        return dict(value)


class MethodComparisonObservableSchema(BaseModel):
    """One quantity of interest extracted from each variant run folder."""

    model_config = ConfigDict(extra="forbid")

    name: str
    variable: str
    source: Literal["disk"] = "disk"
    support: Literal["point", "outlet", "boundary", "cell_mask", "map"] = "point"
    x: float | None = None
    y: float | None = None
    cell_index: int | None = None
    cell_indices: list[int] | None = None
    boundary_id: str | None = None
    time: str | int | None = "all"
    time_window: tuple[str, str] | tuple[float, float] | None = None
    reducer: str | None = None
    time_reducer: str | None = None
    unit: str | None = None

    @field_validator("name", "variable")
    @classmethod
    def _validate_required_text(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("method_comparison.observable value cannot be empty")
        return text

    @field_validator("boundary_id", "reducer", "time_reducer", "unit")
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
            raise ValueError("method_comparison.observable.cell_index must be >= 0")
        return index

    @field_validator("cell_indices")
    @classmethod
    def _validate_cell_indices(cls, value: object) -> list[int] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError(
                "method_comparison.observable.cell_indices must be a non-empty list"
            )
        indices = [int(item) for item in value]
        if any(index < 0 for index in indices):
            raise ValueError("method_comparison.observable.cell_indices must be >= 0")
        return indices

    @model_validator(mode="after")
    def _validate_support_specific_fields(self) -> "MethodComparisonObservableSchema":
        if self.time is not None and self.time_window is not None:
            raise ValueError(
                "method_comparison.observable cannot declare both time and time_window"
            )
        if self.support == "point":
            has_coordinates = self.x is not None and self.y is not None
            if not has_coordinates and self.cell_index is None:
                raise ValueError(
                    "point observables require either x/y coordinates or cell_index"
                )
            if self.reducer is None:
                self.reducer = "nearest_cell"
        elif self.support == "outlet":
            variable_key = self.variable.strip().lower()
            if self.reducer is None:
                self.reducer = "max" if "accumulation" in variable_key else "sum"
        elif self.support == "boundary":
            if self.boundary_id is None and not self.cell_indices:
                raise ValueError(
                    "boundary observables require boundary_id or cell_indices"
                )
            if self.reducer is None:
                self.reducer = "sum"
        elif self.support == "cell_mask":
            if self.reducer is None:
                self.reducer = "sum"
        elif self.support == "map":
            if self.reducer is None:
                self.reducer = "identity"
        return self


class MethodComparisonSectionSchema(BaseModel):
    """Launcher-owned method-comparison section."""

    model_config = ConfigDict(extra="forbid")

    comparison_id: str | None = None
    base_simulation_config: str | None = None
    output_root: str | None = None
    run_variants: bool = True
    continue_on_error: bool = False
    reference_variant: str | None = None
    variant: list[MethodComparisonVariantSchema] = Field(default_factory=list)
    observable: list[MethodComparisonObservableSchema] = Field(default_factory=list)

    @field_validator(
        "comparison_id",
        "base_simulation_config",
        "output_root",
        "reference_variant",
    )
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def _validate_non_empty_lists(self) -> "MethodComparisonSectionSchema":
        if not self.variant:
            raise ValueError("method_comparison.variant must contain at least one item")
        if not self.observable:
            raise ValueError("method_comparison.observable must contain at least one item")
        ids = [variant.id for variant in self.variant]
        if len(set(ids)) != len(ids):
            raise ValueError("method_comparison.variant ids must be unique")
        observable_names = [observable.name for observable in self.observable]
        if len(set(observable_names)) != len(observable_names):
            raise ValueError("method_comparison.observable names must be unique")
        if self.reference_variant is not None and self.reference_variant not in set(ids):
            raise ValueError(
                "method_comparison.reference_variant must match a declared variant id"
            )
        return self


class MethodComparisonConfig(BaseModel):
    """Validated top-level configuration for the method-comparison launcher."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_path: Path
    base_dir: Path
    comparison_root: Path
    base_simulation_config_path: Path | None = None
    method_comparison: MethodComparisonSectionSchema

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> "MethodComparisonConfig":
        """Validate one raw TOML payload and resolve launcher-owned paths."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")
        if "method_comparison" not in raw_toml:
            raise KeyError("Missing required section 'method_comparison'")

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        section = MethodComparisonSectionSchema.model_validate(
            raw_toml["method_comparison"]
        )

        comparison_id = section.comparison_id or resolved_config_path.stem
        section.comparison_id = comparison_id

        if section.output_root is None:
            comparison_root = base_dir / "method_comparison" / comparison_id
        else:
            comparison_root = Path(section.output_root).expanduser()
            if not comparison_root.is_absolute():
                comparison_root = base_dir / comparison_root
        comparison_root = comparison_root.resolve()

        base_simulation_config_path: Path | None = None
        if section.base_simulation_config is not None:
            base_simulation_config_path = Path(
                section.base_simulation_config
            ).expanduser()
            if not base_simulation_config_path.is_absolute():
                base_simulation_config_path = base_dir / base_simulation_config_path
            base_simulation_config_path = base_simulation_config_path.resolve()

        cfg = cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            comparison_root=comparison_root,
            base_simulation_config_path=base_simulation_config_path,
            method_comparison=section,
        )
        cfg._validate_variant_inputs()
        return cfg

    def _validate_variant_inputs(self) -> None:
        """Validate path modes requiring top-level base-config context."""
        for variant in self.method_comparison.variant:
            if not variant.enabled:
                continue
            has_direct_config = variant.simulation_config is not None
            has_generated_config = (
                self.base_simulation_config_path is not None
                and bool(variant.overlay or variant.solver)
            )
            has_run_folder = variant.run_folder is not None
            if not (has_direct_config or has_generated_config or has_run_folder):
                raise ValueError(
                    "Each enabled method_comparison.variant requires "
                    "simulation_config, run_folder, or base_simulation_config "
                    "with overlay/solver"
                )

    def resolve_variant_config_path(
        self,
        variant: MethodComparisonVariantSchema,
    ) -> Path | None:
        """Resolve a variant's declared simulation config path, if any."""
        if variant.simulation_config is None:
            return None
        path = Path(variant.simulation_config).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    def resolve_variant_run_folder(
        self,
        variant: MethodComparisonVariantSchema,
    ) -> Path | None:
        """Resolve a variant's declared existing run folder, if any."""
        if variant.run_folder is None:
            return None
        path = Path(variant.run_folder).expanduser()
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()


__all__ = (
    "MethodComparisonConfig",
    "MethodComparisonObservableSchema",
    "MethodComparisonSectionSchema",
    "MethodComparisonVariantSchema",
)
