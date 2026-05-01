"""Configuration contract for the method-comparison launcher."""

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


class MethodComparisonVariant(HydroModelBase):
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
    overlay: dict[str, Any] = Field(
        default_factory=dict,
        description="TOML overlay applied on top of the base simulation config for this variant.",
    )

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


class MethodComparisonObservable(HydroModelBase):
    """One quantity of interest extracted from each variant run folder."""

    model_config = ConfigDict(extra="forbid")

    name: str
    variable: str
    source: Literal["disk"] = "disk"
    variants: list[str] | None = None
    support: Literal["point", "outlet", "boundary", "cell_mask", "map"] = "point"
    anchor_id: str | None = None
    x: float | None = None
    y: float | None = None
    cell_index: int | None = None
    cell_indices: list[int] | None = None
    boundary_id: str | None = None
    allow_domain_proxy: bool = False
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
            raise ValueError("method_comparison.observable.cell_index must be >= 0")
        return index

    @field_validator("cell_indices")
    @classmethod
    def _validate_cell_indices(cls, value: object) -> list[int] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("method_comparison.observable.cell_indices must be a non-empty list")
        indices = [int(item) for item in value]
        if any(index < 0 for index in indices):
            raise ValueError("method_comparison.observable.cell_indices must be >= 0")
        return indices

    @field_validator("variants")
    @classmethod
    def _validate_variants(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("method_comparison.observable.variants must be a non-empty list")
        cleaned = []
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("method_comparison.observable.variants cannot contain empty ids")
            cleaned.append(text)
        return cleaned

    @model_validator(mode="after")
    def _validate_support_specific_fields(self) -> MethodComparisonObservable:
        if self.time is not None and self.time_window is not None:
            raise ValueError(
                "method_comparison.observable cannot declare both time and time_window"
            )
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


class MethodComparisonSection(HydroModelBase):
    """Launcher-owned method-comparison section."""

    model_config = ConfigDict(extra="forbid")

    comparison_id: str | None = None
    base_simulation_config: str | None = None
    anchors_file: str | None = None
    output_root: str | None = None
    run_variants: bool = True
    continue_on_error: bool = False
    reference_variant: str | None = None
    fine_raster: MethodComparisonFineRaster | None = None
    variant: list[MethodComparisonVariant] = Field(
        default_factory=list,
        description="Solver/mesh method variants to run or reuse for the comparison.",
    )
    observable: list[MethodComparisonObservable] = Field(
        default_factory=list,
        description="Quantities of interest extracted from each variant run folder.",
    )

    @field_validator(
        "comparison_id",
        "base_simulation_config",
        "anchors_file",
        "output_root",
        "reference_variant",
    )
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        return _clean_optional_text(value)

    @model_validator(mode="after")
    def _validate_non_empty_lists(self) -> MethodComparisonSection:
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
            raise ValueError("method_comparison.reference_variant must match a declared variant id")
        variant_ids = set(ids)
        for observable in self.observable:
            if observable.variants is None:
                continue
            missing = sorted(set(observable.variants) - variant_ids)
            if missing:
                missing_text = ", ".join(missing)
                raise ValueError(
                    f"method_comparison.observable.variants contains unknown ids: {missing_text}"
                )
        return self


class MethodComparisonFineRaster(HydroModelBase):
    """Optional common regular-grid rasterization for map comparisons."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    resolution: float | None = None
    extent_mode: Literal["intersection", "union", "reference"] = "intersection"
    interpolation: Literal["linear", "nearest"] = "linear"
    write_geotiff: bool = True

    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, value: object) -> float | None:
        if value is None:
            return None
        resolution = float(value)
        if resolution <= 0.0:
            raise ValueError("method_comparison.fine_raster.resolution must be > 0")
        return resolution

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> MethodComparisonFineRaster:
        if self.enabled and self.resolution is None:
            raise ValueError(
                "method_comparison.fine_raster.resolution is required when fine_raster.enabled=true"
            )
        return self


class MethodComparisonConfig(HydroModelBase):
    """Validated top-level configuration for the method-comparison launcher."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_path: Path
    base_dir: Path
    comparison_root: Path
    base_simulation_config_path: Path | None = None
    anchors_path: Path | None = None
    anchors: dict[str, tuple[float, float]] = Field(
        default_factory=dict,
        description="Resolved anchor id to (x, y) coordinates loaded from anchors_file.",
    )
    method_comparison: MethodComparisonSection

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        config_path: str | Path,
    ) -> MethodComparisonConfig:
        """Validate one raw TOML payload and resolve launcher-owned paths."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")

        resolved_config_path = Path(config_path).expanduser().resolve()
        base_dir = resolved_config_path.parent
        section_payload = (
            raw_toml["method_comparison"] if "method_comparison" in raw_toml else raw_toml
        )
        section = MethodComparisonSection.model_validate(section_payload)

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
            anchors = _load_method_comparison_anchors(anchors_path)
            _apply_observable_anchors(section.observable, anchors)
        elif any(observable.anchor_id is not None for observable in section.observable):
            raise ValueError(
                "method_comparison.observable.anchor_id requires method_comparison.anchors_file"
            )

        cfg = cls(
            config_path=resolved_config_path,
            base_dir=base_dir,
            comparison_root=comparison_root,
            base_simulation_config_path=base_simulation_config_path,
            anchors_path=anchors_path,
            anchors=anchors,
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
            has_generated_config = self.base_simulation_config_path is not None and bool(
                variant.overlay or variant.solver
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
        variant: MethodComparisonVariant,
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
        variant: MethodComparisonVariant,
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
    "MethodComparisonObservable",
    "MethodComparisonSection",
    "MethodComparisonVariant",
)


def _load_method_comparison_anchors(path: Path) -> dict[str, tuple[float, float]]:
    """Load flattened XY anchors from one TOML file."""
    raw_toml = load_toml_with_base_config(path)
    raw_anchors = raw_toml.get("method_comparison_anchors")
    if not isinstance(raw_anchors, Mapping):
        raise KeyError(f"Anchors file '{path}' must expose a [method_comparison_anchors] tree")
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
    observables: list[MethodComparisonObservable],
    anchors: Mapping[str, tuple[float, float]],
) -> None:
    for observable in observables:
        anchor_id = observable.anchor_id
        if anchor_id is None or (observable.x is not None and observable.y is not None):
            continue
        if anchor_id not in anchors:
            raise KeyError(f"Unknown method_comparison anchor_id '{anchor_id}'")
        observable.x, observable.y = anchors[anchor_id]
