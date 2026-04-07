"""Output adapter for MODPATH particle tracking results."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hydromodpy.results.store import ResultStore

logger = logging.getLogger(__name__)


class ModpathOutputAdapter:
    """Read MODPATH pathline / endpoint files and inject into a ResultStore.

    Stores pathline data as Zarr arrays under the ``pathlines/`` subgroup:
    x, y, z, time — each shaped ``(n_particles, max_steps)`` with NaN
    padding for particles that terminate early.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: ResultStore,
        *,
        model_name: str | None = None,
    ) -> None:
        """Read MODPATH output files and write pathlines into the store."""
        from flopy.utils import PathlineFile, EndpointFile

        solver_output_dir = Path(solver_output_dir)

        # Try pathline file first
        pth_files = list(solver_output_dir.glob("*.mppth")) + list(
            solver_output_dir.glob("*pathline*")
        )
        if pth_files:
            self._extract_pathlines(sim_id, store, pth_files[0])

        # Also try endpoint file
        ept_files = list(solver_output_dir.glob("*.mpend")) + list(
            solver_output_dir.glob("*endpoint*")
        )
        if ept_files:
            self._extract_endpoints(sim_id, store, ept_files[0])

    def _extract_pathlines(
        self,
        sim_id: str,
        store: ResultStore,
        pth_path: Path,
    ) -> None:
        """Read pathline file and write x/y/z/time arrays to Zarr."""
        from flopy.utils import PathlineFile

        pth = PathlineFile(str(pth_path))
        all_data = pth.get_alldata()

        if not all_data:
            logger.debug("Empty pathline file %s", pth_path)
            return

        n_particles = len(all_data)
        max_steps = max(len(p) for p in all_data)

        x = np.full((n_particles, max_steps), np.nan, dtype="float64")
        y = np.full((n_particles, max_steps), np.nan, dtype="float64")
        z = np.full((n_particles, max_steps), np.nan, dtype="float64")
        t = np.full((n_particles, max_steps), np.nan, dtype="float64")

        for i, particle in enumerate(all_data):
            n = len(particle)
            x[i, :n] = particle["x"]
            y[i, :n] = particle["y"]
            z[i, :n] = particle["z"]
            t[i, :n] = particle["time"]

        grp = store.open_zarr_group(sim_id, mode="a")
        pathlines_grp = grp.require_group("pathlines")
        for name, arr in [("x", x), ("y", y), ("z", z), ("time", t)]:
            pathlines_grp.create_array(
                name, data=arr, overwrite=True,
            )

        logger.info(
            "Extracted %d pathlines (max %d steps) for sim %s",
            n_particles, max_steps, sim_id,
        )

    def _extract_endpoints(
        self,
        sim_id: str,
        store: ResultStore,
        ept_path: Path,
    ) -> None:
        """Read endpoint file and write as a single-step pathline."""
        from flopy.utils import EndpointFile

        ept = EndpointFile(str(ept_path))
        all_data = ept.get_alldata()

        if len(all_data) == 0:
            logger.debug("Empty endpoint file %s", ept_path)
            return

        grp = store.open_zarr_group(sim_id, mode="a")
        pathlines_grp = grp.require_group("pathlines")

        pathlines_grp.create_array(
            "endpoint_x", data=all_data["x0"].astype("float64"), overwrite=True,
        )
        pathlines_grp.create_array(
            "endpoint_y", data=all_data["y0"].astype("float64"), overwrite=True,
        )
        pathlines_grp.create_array(
            "endpoint_z", data=all_data["z0"].astype("float64"), overwrite=True,
        )
        pathlines_grp.create_array(
            "endpoint_time", data=all_data["time"].astype("float64"), overwrite=True,
        )

        logger.info("Extracted %d endpoints for sim %s", len(all_data), sim_id)

    def derive(
        self,
        sim_id: str,
        store: ResultStore,
        config: dict | None = None,
    ) -> None:
        """No derived variables for particle tracking."""
        pass
