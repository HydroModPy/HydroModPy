"""CLI adapter for ``hmp run <config.toml>`` (batch regional workflow).

Domain logic lives in :mod:`launchers.regional_lab`
(will migrate to ``analysis/batch/`` in Phase 5).
"""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path) -> dict:
    """Run a multi-site batch campaign from a TOML file."""
    from hydromodpy.analysis.batch.runtime import RegionalLabLauncher

    return RegionalLabLauncher(config_path).run()
