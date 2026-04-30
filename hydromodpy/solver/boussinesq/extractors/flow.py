"""Output adapter for Boussinesq solver results."""

from __future__ import annotations

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

        self._write_surface_elevation(sim_id, store, solver_output_dir, n_cells)

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

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        n_cells: int,
    ) -> None:
        """Write surface_top from Boussinesq summary for derived variables."""
        try:
            import json as _json

            summary_path = solver_output_dir / "_boussinesq_summary.json"
            if not summary_path.exists():
                return

            summary = _json.loads(summary_path.read_text(encoding="utf-8"))
            z_top = summary.get("z_top_m")
            if z_top is not None:
                top = np.full(n_cells, float(z_top), dtype="float64")
            else:
                return

            grp = store._open_zarr_group(sim_id)
            if "mesh" not in grp:
                grp.create_group("mesh")
            mesh = grp["mesh"]
            mesh.create_array("surface_top", data=top, overwrite=True)
            z_flat = np.array([float(z_top), float(z_top) - 10.0])
            mesh.create_array("z_interfaces", data=z_flat, overwrite=True)
            mesh.attrs["n_cells"] = int(n_cells)
            mesh.attrs["n_layers"] = 1
        except Exception:
            logger.debug("Could not write surface elevation for Boussinesq sim %s", sim_id)

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
        try:
            compute_derived(sim_id, store, boussinesq_cfg)
        except Exception:
            logger.debug(
                "Derived variable computation skipped for Boussinesq sim %s "
                "(mesh may not be registered in store)",
                sim_id,
            )
