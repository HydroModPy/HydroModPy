"""Output adapter for Boussinesq solver results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.time import CF_EPOCH, CF_TIME_UNITS, cf_time_axis_seconds
from hydromodpy.solver.boussinesq.export_payload import first_period_snapshot
from hydromodpy.solver.boussinesq.extractors.descent import (
    raster_grid_shape,
    whitebox_d8_descent,
    write_raster_descent,
)

logger = get_logger(__name__)


class BoussinesqOutputAdapter:
    """Read Boussinesq state history and inject fields into a Catalog.

    Expects a solver output directory with ``_boussinesq_state_history.npz``
    (head history, derived fluxes) and ``_boussinesq_summary.json``
    (convergence metadata). ``Boussinesq.processing()`` writes both files at
    the end of the solve, mirroring the MODFLOW lifecycle where the run step
    is the only writer of solver outputs.

    The extractor also stores the descent D of a raster run, so the
    accumulation fluxes are routed on read as on MODFLOW.
    """

    solver_name = "boussinesq"
    category = "integrated"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        budget_terms: BudgetKeep = BudgetKeep.everything(),
        start_datetime: object | None = None,
    ) -> None:
        """Read .npz state history and write head and budget fields to the store.

        ``budget_terms`` says which per-cell budget terms are written; the
        lumped budget table always holds every term.
        """
        solver_output_dir = Path(solver_output_dir)
        npz_path = solver_output_dir / "_boussinesq_state_history.npz"

        if not npz_path.exists():
            raise FileNotFoundError(f"No _boussinesq_state_history.npz in {solver_output_dir}")

        with np.load(npz_path) as payload:
            head_history = payload.get("head_history_m")
            if head_history is None:
                head_history = payload.get("final_head_m")
                if head_history is not None:
                    head_history = head_history.reshape(1, -1)

            if head_history is None:
                raise KeyError(f"No head data in {npz_path}")

            if head_history.ndim == 1:
                head_history = head_history.reshape(1, -1)

            # The store stamps each stress period at its end, as the MODFLOW
            # extractors do: the initial state of a transient history closes no
            # period, so it stays in the state group only.
            first = first_period_snapshot(payload, n_snapshots=head_history.shape[0])
            n_timesteps = head_history.shape[0] - first
            n_cells = head_history.shape[1]
            z_top_m = payload.get("z_top_m")
            z_bottom_m = payload.get("z_bottom_m")
            cell_area_m2 = payload.get("cell_area_m2")
            time_values = payload.get("snapshot_elapsed_seconds")
            if time_values is None or len(time_values) < first + n_timesteps:
                raise KeyError(f"No snapshot_elapsed_seconds time axis in {npz_path}")
            # Write /time at period resolution (one entry per head slice). The
            # payload carries relative elapsed seconds, so anchor to the launcher
            # start_datetime for a real calendar axis instead of seconds since 1970.
            writer = getattr(store, "write_time", None)
            if writer is None:
                raise TypeError("Simulation store must implement write_time().")
            values = cf_time_axis_seconds(
                np.asarray(time_values[first : first + n_timesteps], dtype=float),
                start_datetime,
            )
            writer(sim_id, values, epoch=CF_EPOCH, units=CF_TIME_UNITS)

            logger.info(
                "Extracting Boussinesq results: %d timesteps, %d cells",
                n_timesteps,
                n_cells,
            )

            head_stack = np.asarray(
                head_history[first : first + n_timesteps], dtype="float64"
            ).reshape(n_timesteps, 1, n_cells)
            store.write_field_stack(sim_id, "head", head_stack)

            self._persist_state_history(sim_id, store, payload)
            components = self._budget_components(
                payload,
                n_timesteps=n_timesteps,
                n_cells=n_cells,
                cell_area_m2=cell_area_m2,
                first_snapshot=first,
            )
            # The lumped per-component budget holds every term, whatever the
            # per-cell policy: the catchment scalars (discharge, well pumping)
            # are derived from it.
            self._write_budget_table(sim_id, store, components, n_timesteps=n_timesteps)
            self._write_budget_fields(sim_id, store, components, budget_terms=budget_terms)

        z_top = self._write_surface_elevation(
            sim_id,
            store,
            solver_output_dir,
            n_cells,
            z_top_m=z_top_m,
            z_bottom_m=z_bottom_m,
        )
        self._write_descent(sim_id, store, z_top, cell_area_m2=cell_area_m2)

    @staticmethod
    def _persist_state_history(sim_id: str, store: Any, payload) -> None:
        """Write all Boussinesq state arrays to a ``boussinesq_state`` Zarr group."""
        sz = store.open_zarr(sim_id)
        try:
            grp = sz.root
            state_grp = grp.require_group("boussinesq_state")
            for key in payload.files:
                arr = np.asarray(payload[key])
                # A restart array shares no axis with its neighbours, so it
                # names its own: an unnamed axis makes the store unopenable.
                state_grp.create_array(
                    key,
                    data=arr,
                    dimension_names=tuple(f"{key}_dim{axis}" for axis in range(arr.ndim)),
                    overwrite=True,
                )
            logger.debug("Persisted %d Boussinesq state arrays to store", len(payload.files))
        finally:
            sz.close()

    @staticmethod
    def _budget_components(
        payload,
        *,
        n_timesteps: int,
        n_cells: int,
        cell_area_m2: np.ndarray | None,
        first_snapshot: int = 0,
    ) -> dict[str, np.ndarray]:
        """Return the per-cell budget stacks in canonical solver orientation.

        Each entry is ``(n_timesteps, n_cells)`` in m3/s, one row per stress
        period from ``first_snapshot`` on, and keeps the sign the Boussinesq
        residual uses: ``recharge`` and ``well`` are positive when water enters
        the aquifer, ``drain``, ``surface_excess`` and ``constant_head`` are
        positive when water leaves it.
        """
        area = None if cell_area_m2 is None else np.asarray(cell_area_m2, dtype=float).reshape(-1)
        if area is not None and area.size != int(n_cells):
            raise ValueError(
                f"Boussinesq cell_area_m2 has {area.size} cells; expected {int(n_cells)}"
            )

        def _history(name: str) -> np.ndarray | None:
            values = payload.get(name)
            if values is None:
                return None
            arr = np.asarray(values, dtype=float)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.shape[1] != int(n_cells):
                raise ValueError(
                    f"Boussinesq array {name!r} has {arr.shape[1]} cells; expected {int(n_cells)}"
                )
            stop = int(first_snapshot) + int(n_timesteps)
            if arr.shape[0] < stop:
                raise ValueError(
                    f"Boussinesq array {name!r} has {arr.shape[0]} timesteps; "
                    f"expected at least {stop}"
                )
            return arr[int(first_snapshot) : stop]

        def _rate_to_flux(name: str, label: str) -> np.ndarray | None:
            rate = _history(name)
            if rate is None:
                return None
            if area is None:
                raise KeyError(f"Boussinesq {label} history requires cell_area_m2")
            return rate * area.reshape(1, -1)

        candidates = {
            "recharge": _rate_to_flux("recharge_rate_history_m_s", "recharge"),
            "drain": _history("drainage_flux_history_m3_s"),
            "well": _history("well_flux_history_m3_s"),
            "surface_excess": _rate_to_flux("saturation_excess_history_m_s", "saturation excess"),
            "constant_head": _history("prescribed_head_flux_history_m3_s"),
        }
        return {name: stack for name, stack in candidates.items() if stack is not None}

    # Components whose positive values leave the aquifer. The lumped budget
    # follows the MODFLOW convention (flux_in = what enters the model), so
    # these are flipped before the in/out split.
    _OUTFLOW_POSITIVE_COMPONENTS = frozenset({"drain", "surface_excess", "constant_head"})

    @staticmethod
    def _write_budget_table(
        sim_id: str,
        store: Any,
        components: dict[str, np.ndarray],
        *,
        n_timesteps: int,
    ) -> None:
        """Write the lumped per-component budget rows (m3/s) for every timestep."""
        records: list[dict[str, Any]] = []
        for name, stack in components.items():
            signed = (
                -stack if name in BoussinesqOutputAdapter._OUTFLOW_POSITIVE_COMPONENTS else stack
            )
            for t in range(int(n_timesteps)):
                step = signed[t]
                records.append(
                    {
                        "timestep": t,
                        "zone_id": "0",
                        "component": name,
                        "flux_in": float(np.maximum(step, 0.0).sum()),
                        "flux_out": abs(float(np.minimum(step, 0.0).sum())),
                        "unit": "m3/s",
                    }
                )
        if records:
            records.sort(key=lambda record: record["timestep"])
            store.write_budgets(sim_id, records)

    @staticmethod
    def _write_budget_fields(
        sim_id: str,
        store: Any,
        components: dict[str, np.ndarray],
        *,
        budget_terms: BudgetKeep,
    ) -> None:
        """Write the per-cell budget terms the run keeps, with solver units.

        ``surface_excess`` is written like any other term: the seepage mask is
        rebuilt on read from it. The ``budget/`` group then records the policy
        and the terms kept.
        """
        written: list[str] = []
        for name, stack in components.items():
            if not budget_terms.keeps(name):
                continue
            # The registry signs a constant-head flux positive into the aquifer,
            # as MODFLOW writes it; the solver signs it positive out.
            signed = -stack if name == "constant_head" else stack
            values = signed.reshape(signed.shape[0], 1, -1) if name == "well" else signed
            store.write_field_stack(sim_id, name, values, subgroup="budget")
            written.append(name)

        sz = store.open_zarr(sim_id)
        try:
            sz.write_budget_policy(budget_terms, written)
        finally:
            sz.close()

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        n_cells: int,
        *,
        z_top_m: np.ndarray | None,
        z_bottom_m: np.ndarray | None,
    ) -> np.ndarray:
        """Write mesh/topography from the Boussinesq payload or summary; return the top."""
        summary: dict[str, Any] = {}
        if z_top_m is None or z_bottom_m is None:
            summary_path = solver_output_dir / "_boussinesq_summary.json"
            if not summary_path.exists():
                raise FileNotFoundError(
                    f"No Boussinesq surface metadata found for sim {sim_id}: {summary_path}"
                )

            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Could not parse Boussinesq summary: {summary_path}") from exc
        raw_z_top = z_top_m if z_top_m is not None else summary.get("z_top_m")
        raw_z_bottom = z_bottom_m if z_bottom_m is not None else summary.get("z_bottom_m")
        if raw_z_top is None or raw_z_bottom is None:
            raise KeyError(
                f"Boussinesq surface metadata missing z_top_m/z_bottom_m for sim {sim_id}"
            )
        z_top = np.asarray(raw_z_top, dtype="float64").reshape(-1)
        z_bottom = np.asarray(raw_z_bottom, dtype="float64").reshape(-1)
        if z_top.size == 1:
            z_top = np.full(n_cells, float(z_top[0]), dtype="float64")
        if z_bottom.size == 1:
            z_bottom = np.full(n_cells, float(z_bottom[0]), dtype="float64")
        if z_top.size != int(n_cells) or z_bottom.size != int(n_cells):
            raise ValueError(
                "Boussinesq surface arrays have incompatible sizes: "
                f"z_top={z_top.size}, z_bottom={z_bottom.size}, n_cells={int(n_cells)}"
            )

        sz = store.open_zarr(sim_id)
        try:
            sz.write_topography(
                topography=z_top,
                z_interfaces=np.vstack([z_top, z_bottom]),
                n_cells=int(n_cells),
                n_layers=1,
            )
        finally:
            sz.close()
        return z_top

    @staticmethod
    def _write_descent(
        sim_id: str,
        store: Any,
        z_top: np.ndarray,
        *,
        cell_area_m2: np.ndarray | None,
    ) -> bool:
        """Store the descent D of a raster run; return whether it was stored.

        Without a raster shape or without Whitebox, no D is stored and the log
        says why: the accumulation fluxes of the run are then unavailable on
        read, never routed some other way.
        """
        metadata = store.read_geographic_metadata(sim_id)
        shape, reason = raster_grid_shape(metadata, int(z_top.size), cell_area_m2)
        if shape is None:
            logger.info(
                "Run %s stores no descent: %s. Its accumulation fluxes are unavailable.",
                sim_id,
                reason,
            )
            return False
        try:
            receiver, surface = whitebox_d8_descent(z_top, shape)
        except Exception:
            logger.warning(
                "Run %s stores no descent: the Whitebox D8 pointer of its top failed. "
                "Its accumulation fluxes are unavailable.",
                sim_id,
                exc_info=True,
            )
            return False
        sz = store.open_zarr(sim_id)
        try:
            write_raster_descent(sz, top=z_top, receiver=receiver, surface=surface)
        finally:
            sz.close()
        return True
