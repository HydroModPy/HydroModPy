"""Description lookup for generated comparison TOML exports."""

from __future__ import annotations

from collections.abc import Sequence

from hydromodpy.analysis.comparison.config import (
    ComparisonFineRaster,
    ComparisonObservable,
)
from hydromodpy.analysis.comparison.experiment_config import (
    ComparisonAuditConfig,
    ComparisonExecutionConfig,
    ComparisonSection,
    ComparisonSimulationConfig,
)
from hydromodpy.core.toml_io.descriptions import (
    clean_description,
    model_description_for_path,
    model_field_description,
    root_config_description_for_path,
)


def comparison_description_for_path(parts: Sequence[str]) -> str | None:
    """Return a description for a comparison TOML path when one is known."""
    if not parts:
        return None
    if parts[0] != "comparison":
        return root_config_description_for_path(parts)

    comparison_parts = tuple(str(part) for part in parts[1:])
    if not comparison_parts:
        return clean_description(ComparisonSection.__doc__)

    first = comparison_parts[0]
    if first == "execution":
        if len(comparison_parts) == 1:
            return model_field_description(ComparisonSection, "execution")
        return model_description_for_path(
            ComparisonExecutionConfig,
            comparison_parts[1:],
        )
    if first == "audit":
        if len(comparison_parts) == 1:
            return model_field_description(ComparisonSection, "audit")
        return model_description_for_path(ComparisonAuditConfig, comparison_parts[1:])
    if first == "simulation":
        if len(comparison_parts) == 1:
            return model_field_description(ComparisonSection, "simulation")
        if comparison_parts[1] == "overlay":
            if len(comparison_parts) == 2:
                return model_field_description(ComparisonSimulationConfig, "overlay")
            return root_config_description_for_path(comparison_parts[2:])
        return model_description_for_path(
            ComparisonSimulationConfig,
            comparison_parts[1:],
        )
    if first == "observable":
        if len(comparison_parts) == 1:
            return model_field_description(ComparisonSection, "observable")
        return model_description_for_path(ComparisonObservable, comparison_parts[1:])
    if first == "fine_raster":
        if len(comparison_parts) == 1:
            return model_field_description(ComparisonSection, "fine_raster")
        return model_description_for_path(ComparisonFineRaster, comparison_parts[1:])
    if first == "base_simulation_overlay":
        if len(comparison_parts) == 1:
            return model_field_description(ComparisonSection, "base_simulation_overlay")
        return root_config_description_for_path(comparison_parts[1:])

    return model_description_for_path(ComparisonSection, comparison_parts)


__all__ = ["comparison_description_for_path"]
