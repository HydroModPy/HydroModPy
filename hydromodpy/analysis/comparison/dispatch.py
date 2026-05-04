"""Dispatch comparison configs to the matching comparison launcher."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def run_comparison_config(config_path: str | Path) -> dict[str, Any]:
    """Run a comparison config through the appropriate launcher."""
    return resolve_comparison_launcher(config_path).run()


def resolve_comparison_launcher(config_path: str | Path) -> Any:
    """Instantiate the comparison launcher matching the TOML section."""
    resolved_path = Path(config_path).expanduser().resolve()
    raw_toml = load_toml_with_base_config(resolved_path)
    has_comparison = "comparison" in raw_toml

    if not has_comparison:
        raise KeyError("Comparison config must declare [comparison].")

    section = raw_toml["comparison"]
    if not isinstance(section, Mapping):
        raise ValueError("[comparison] must be a mapping")
    has_simulation = "simulation" in section
    has_variant = "variant" in section
    if has_variant:
        raise ValueError(
            "[[comparison.variant]] has been removed; use [[comparison.simulation]]."
        )
    if not has_simulation:
        raise KeyError("Comparison config must declare [[comparison.simulation]].")

    from hydromodpy.analysis.comparison.experiment_launcher import (
        SimulationComparisonLauncher,
    )

    return SimulationComparisonLauncher(resolved_path)


__all__ = ("resolve_comparison_launcher", "run_comparison_config")
