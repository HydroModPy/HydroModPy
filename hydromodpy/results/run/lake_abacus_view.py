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

    With ``lake_id=None`` the lake holding the most water at full pool is returned,
    not the first one persisted: a reservoir and its pre-retenue differ by more than
    an order of magnitude in storage, and defaulting to whichever happened to be
    written first shows the small one and hides the one being modelled. ``lake_ids``
    carries every persisted lake so a caller can iterate. Raises ``KeyError`` when no
    lake abacus was persisted for this run.
    """
    sz = run._catalog.open_zarr(run._sim_id)
    try:
        lakes = [str(name) for name in sz.lake_abacus_lakes()]
        if not lakes:
            raise KeyError("no lake abacus persisted for this run")
        if lake_id is None:
            lake_id = max(lakes, key=lambda name: _full_pool_volume(sz, name))
        payload = dict(sz.read_lake_abacus(lake_id))
        # Name the lake that was actually read: a caller (or a figure title) cannot
        # otherwise tell which curve it got.
        payload.setdefault("lake_id", str(lake_id))
        payload.setdefault("lake_ids", lakes)
        return payload
    finally:
        sz.close()


def _full_pool_volume(store: object, lake_id: str) -> float:
    """Reference storage at the top of one lake's abacus, 0.0 when unreadable."""
    try:
        volume = store.read_lake_abacus(lake_id).get("real_volume")
    except (KeyError, OSError, ValueError):
        return 0.0
    return float(volume[-1]) if volume is not None and len(volume) else 0.0
