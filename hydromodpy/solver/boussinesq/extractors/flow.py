"""Output adapter for Boussinesq solver results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class BoussinesqOutputAdapter:
    """Read Boussinesq state history and inject fields into a SimulationCatalog.

    Expects a solver output directory with ``_boussinesq_state_history.npz``
    (head history, derived fluxes) and ``_boussinesq_summary.json``
    (convergence metadata). ``Boussinesq.processing()`` writes both files at
    the end of the solve, mirroring the MODFLOW lifecycle where the run step
    is the only writer of solver outputs.
    """

    solver_name = "boussinesq"
    category = "integrated"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
    ) -> None:
        """Read .npz state history and write head fields to the store."""
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

            n_timesteps = head_history.shape[0]
            n_cells = head_history.shape[1]
            z_top_m = payload.get("z_top_m")
            z_bottom_m = payload.get("z_bottom_m")
            cell_area_m2 = payload.get("cell_area_m2")
            time_values = payload.get("snapshot_elapsed_seconds")
            if time_values is None or len(time_values) < n_timesteps:
                raise KeyError(f"No snapshot_elapsed_seconds time axis in {npz_path}")
            writer = getattr(store, "write_time", None)
            if writer is None:
                raise TypeError("Simulation store must implement write_time().")
            writer(
                sim_id, np.rint(np.asarray(time_values[:n_timesteps], dtype=float)).astype("int64")
            )

            logger.info(
                "Extracting Boussinesq results: %d timesteps, %d cells",
                n_timesteps,
                n_cells,
            )

            for t in range(n_timesteps):
                values = head_history[t].reshape(1, n_cells)
                store.write_field(
                    sim_id,
                    "head",
                    t,
                    values,
                    n_timesteps=n_timesteps if t == 0 else None,
                )

            self._persist_state_history(sim_id, store, payload)
            self._write_budget_fields(
                sim_id,
                store,
                payload,
                n_timesteps=n_timesteps,
                n_cells=n_cells,
                cell_area_m2=cell_area_m2,
            )

        self._write_surface_elevation(
            sim_id,
            store,
            solver_output_dir,
            n_cells,
            z_top_m=z_top_m,
            z_bottom_m=z_bottom_m,
        )

    @staticmethod
    def _persist_state_history(sim_id: str, store: Any, payload) -> None:
        """Write all Boussinesq state arrays to a ``boussinesq_state`` Zarr group."""
        sz = store.open_zarr(sim_id)
        try:
            grp = sz.root
            state_grp = grp.require_group("boussinesq_state")
            for key in payload.files:
                arr = np.asarray(payload[key])
                state_grp.create_array(key, data=arr, overwrite=True)
            logger.debug("Persisted %d Boussinesq state arrays to store", len(payload.files))
        finally:
            sz.close()

    @staticmethod
    def _write_budget_fields(
        sim_id: str,
        store: Any,
        payload,
        *,
        n_timesteps: int,
        n_cells: int,
        cell_area_m2: np.ndarray | None,
    ) -> None:
        """Write canonical Boussinesq budget fields with solver units."""
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
            if arr.shape[0] < int(n_timesteps):
                raise ValueError(
                    f"Boussinesq array {name!r} has {arr.shape[0]} timesteps; "
                    f"expected at least {int(n_timesteps)}"
                )
            return arr[:n_timesteps]

        recharge_rate = _history("recharge_rate_history_m_s")
        if recharge_rate is not None:
            if area is None:
                raise KeyError("Boussinesq recharge history requires cell_area_m2")
            recharge_flux = recharge_rate * area.reshape(1, -1)
            for timestep, values in enumerate(recharge_flux):
                store.write_field(
                    sim_id,
                    "recharge",
                    timestep,
                    values,
                    n_timesteps=n_timesteps if timestep == 0 else None,
                    subgroup="budget",
                )

        drainage_flux = _history("drainage_flux_history_m3_s")
        if drainage_flux is not None:
            for timestep, values in enumerate(drainage_flux):
                store.write_field(
                    sim_id,
                    "drain",
                    timestep,
                    values,
                    n_timesteps=n_timesteps if timestep == 0 else None,
                    subgroup="budget",
                )

        well_flux = _history("well_flux_history_m3_s")
        if well_flux is not None:
            for timestep, values in enumerate(well_flux):
                store.write_field(
                    sim_id,
                    "well",
                    timestep,
                    values.reshape(1, -1),
                    n_timesteps=n_timesteps if timestep == 0 else None,
                    subgroup="budget",
                )

        saturation_excess = _history("saturation_excess_history_m_s")
        if saturation_excess is not None:
            if area is None:
                raise KeyError("Boussinesq saturation excess history requires cell_area_m2")
            surface_excess_flux = saturation_excess * area.reshape(1, -1)
            for timestep, values in enumerate(surface_excess_flux):
                store.write_field(
                    sim_id,
                    "surface_excess",
                    timestep,
                    values,
                    n_timesteps=n_timesteps if timestep == 0 else None,
                    subgroup="budget",
                )

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        n_cells: int,
        *,
        z_top_m: np.ndarray | None,
        z_bottom_m: np.ndarray | None,
    ) -> None:
        """Write surface_top from Boussinesq summary for derived variables."""
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
            mesh = sz.root.require_group("mesh")
            mesh.create_array("surface_top", data=z_top, overwrite=True)
            mesh.create_array(
                "z_interfaces",
                data=np.vstack([z_top, z_bottom]),
                overwrite=True,
            )
            mesh.attrs["n_cells"] = int(n_cells)
            mesh.attrs["n_layers"] = 1
        finally:
            sz.close()

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None:
        """Compute solver-adjacent derived fields (seepage areas, etc.).

        Watertable elevation/depth are produced by the workflow registry
        (:class:`DeriveStep`); this hook only handles fields that the
        registry does not own.
        """
        from hydromodpy.simulation.extraction.extractors.derived import compute_derived

        cfg = config or {}
        boussinesq_cfg = {
            "seepage_areas": cfg.get("seepage_areas", False),
            "groundwater_flux": False,
            "accumulation_flux": False,
            "concentration_seepage": False,
            "mass_seepage": False,
            "mass_accumulated": False,
        }
        compute_derived(sim_id, store, boussinesq_cfg)
