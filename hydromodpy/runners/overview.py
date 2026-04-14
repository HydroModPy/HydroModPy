"""CLI adapter for ``hmp run <config.toml>`` (overview workflow)."""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path) -> dict:
    """Generate a watershed identity card from a TOML file."""
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

    return DataOverviewLauncher(config_path).run()
