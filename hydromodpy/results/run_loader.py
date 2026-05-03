"""Factory entry points to build a :class:`Run` from a config source."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


class RunLoaderAdapter:
    """Build a :class:`Run` view from a TOML / JSON / dict config payload."""

    @classmethod
    def from_toml(cls, toml_path: str | Path, sim_id: str) -> Run:
        """Return the Run view for ``sim_id`` in the workspace declared by a TOML."""
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.results.run import Run

        return Run(sim_id, SimulationCatalog.from_toml(toml_path))

    @classmethod
    def from_json(cls, payload: str | bytes, sim_id: str) -> Run:
        """Return the Run view for ``sim_id`` in the workspace declared by a JSON config."""
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.results.run import Run

        return Run(sim_id, SimulationCatalog.from_json(payload))

    @classmethod
    def from_dict(cls, payload: dict, sim_id: str) -> Run:
        """Return the Run view for ``sim_id`` in the workspace declared by a dict config."""
        from hydromodpy.results.catalog import SimulationCatalog
        from hydromodpy.results.run import Run

        return Run(sim_id, SimulationCatalog.from_dict(payload))
