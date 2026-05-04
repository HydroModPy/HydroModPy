"""Dispatch comparison configs to the canonical or legacy launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config


def run_comparison_config(config_path: str | Path) -> dict[str, Any]:
    """Run a comparison config through the appropriate launcher.

    ``[comparison]`` is the canonical public workflow. ``[method_comparison]``
    remains supported here as a legacy compatibility path while those configs
    are migrated.
    """
    return resolve_comparison_launcher(config_path).run()


def resolve_comparison_launcher(config_path: str | Path) -> Any:
    """Instantiate the comparison launcher matching the TOML section."""
    resolved_path = Path(config_path).expanduser().resolve()
    raw_toml = load_toml_with_base_config(resolved_path)
    has_comparison = "comparison" in raw_toml
    has_method_comparison = "method_comparison" in raw_toml

    if has_comparison and has_method_comparison:
        raise ValueError(
            "Comparison config cannot declare both [comparison] and "
            "[method_comparison]. Use [comparison] for new configs."
        )
    if has_comparison:
        from hydromodpy.analysis.comparison.experiment_launcher import (
            SimulationComparisonLauncher,
        )

        return SimulationComparisonLauncher(resolved_path)
    if has_method_comparison:
        from hydromodpy.analysis.comparison.orchestrator import MethodComparisonLauncher

        return MethodComparisonLauncher(resolved_path)

    raise KeyError(
        "Comparison config must declare [comparison] or legacy [method_comparison]."
    )


__all__ = ("resolve_comparison_launcher", "run_comparison_config")
