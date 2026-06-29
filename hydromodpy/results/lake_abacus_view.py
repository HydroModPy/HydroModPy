"""Read the persisted lake abacus comparison for a run.

A module-level view (not a ``Run`` method, to keep the ``Run`` public surface
under the CLAUDE.md cap) that opens the per-sim Zarr and returns the reference vs
simulated abacus arrays a lake used during ``bed_reconstruction``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = ["run_lake_abacus"]


def run_lake_abacus(run: Run, lake_id: str | None = None) -> dict:
    """Return ``{stage, real_volume, real_sarea, sim_volume, sim_sarea, ...}``.

    With ``lake_id=None`` the first reconstructed lake is returned. Raises
    ``KeyError`` when no lake abacus was persisted for this run.
    """
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        if lake_id is None:
            lakes = sz.lake_abacus_lakes()
            if not lakes:
                raise KeyError("no lake abacus persisted for this run")
            lake_id = lakes[0]
        return sz.read_lake_abacus(lake_id)
    finally:
        sz.close()
