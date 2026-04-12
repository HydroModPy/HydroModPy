"""Output adapter for Boussinesq solver results."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from hydromodpy.results.store import ResultStore

logger = logging.getLogger(__name__)


class BoussinesqOutputAdapter:
    """Read Boussinesq state history and inject fields into a ResultStore.

    Expects a solver output directory with ``_boussinesq_state_history.npz``
    (head history, derived fluxes) and ``_boussinesq_summary.json``
    (convergence metadata).  These are written by
    ``Boussinesq.post_processing()`` which the adapter calls after the
    numerical solve.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: ResultStore,
    ) -> None:
        """Read .npz state history and write head fields to the store."""
        solver_output_dir = Path(solver_output_dir)
        npz_path = solver_output_dir / "_boussinesq_state_history.npz"

        if not npz_path.exists():
            logger.warning("No _boussinesq_state_history.npz in %s", solver_output_dir)
            return

        with np.load(npz_path) as payload:
            head_history = payload.get("head_history_m")
            if head_history is None:
                head_history = payload.get("final_head_m")
                if head_history is not None:
                    head_history = head_history.reshape(1, -1)

            if head_history is None:
                logger.warning("No head data in %s", npz_path)
                return

            if head_history.ndim == 1:
                head_history = head_history.reshape(1, -1)

            n_timesteps = head_history.shape[0]
            n_cells = head_history.shape[1]

            logger.info(
                "Extracting Boussinesq results: %d timesteps, %d cells",
                n_timesteps, n_cells,
            )

            # Write head as a 1-layer field.
            for t in range(n_timesteps):
                values = head_history[t].reshape(1, n_cells)  # (1 layer, n_cells)
                store.write_field(
                    sim_id, "head", t, values,
                    n_timesteps=n_timesteps if t == 0 else None,
                )

            # Persist all state history arrays into a Zarr group so that
            # display suites can read them without the .npz file.
            self._persist_state_history(sim_id, store, payload)

        # Write surface elevation from the Boussinesq summary or bundle.
        self._write_surface_elevation(sim_id, store, solver_output_dir, n_cells)

    @staticmethod
    def _persist_state_history(sim_id: str, store: ResultStore, payload) -> None:
        """Write all Boussinesq state arrays to a ``boussinesq_state`` Zarr group."""
        try:
            grp = store._zarr_root[str(sim_id)]
            if "boussinesq_state" not in grp:
                grp.create_group("boussinesq_state")
            state_grp = grp["boussinesq_state"]
            for key in payload.files:
                arr = np.asarray(payload[key])
                state_grp.create_array(key, data=arr, overwrite=True)
            logger.debug("Persisted %d Boussinesq state arrays to store", len(payload.files))
        except Exception:
            logger.debug("Failed to persist Boussinesq state history", exc_info=True)

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: ResultStore,
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
                # Try reading from the npz (no z_top in summary, estimate from head).
                return

            grp = store._zarr_root[str(sim_id)]
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
        store: ResultStore,
        config: dict | None = None,
    ) -> None:
        """Compute watertable_elevation and watertable_depth from head.

        Boussinesq is a single-layer model so watertable_elevation == head.
        Depth requires the mesh z_top which is not in the store; instead we
        read the _boussinesq_state_history.npz if head_history and the mesh
        are both available via the store.
        """
        from hydromodpy.simulation.results.extractors.derived import compute_derived

        cfg = config or {}
        # Only compute what makes sense for a single-layer model.
        boussinesq_cfg = {
            "watertable_elevation": cfg.get("watertable_elevation", True),
            "watertable_depth": cfg.get("watertable_depth", True),
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
