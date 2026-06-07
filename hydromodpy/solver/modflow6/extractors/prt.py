"""Output adapter for MODFLOW 6 PRT particle tracking results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.prt_tracks import (
    read_prt_track_csv,
    read_time_units_from_tdis,
)

logger = get_logger(__name__)


class Modflow6PrtOutputAdapter:
    """Read MF6 PRT track CSV files and inject particle tracks into a catalog.

    Stored Zarr layout matches the existing MODPATH extractor:
    ``particles/x``, ``particles/y``, ``particles/z`` and ``particles/time``
    are two-dimensional arrays shaped ``(n_particles, max_steps)`` with NaN
    padding for shorter tracks.
    """

    solver_name = "modflow6_prt"
    category = "distributed"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        model_name: str | None = None,
    ) -> None:
        """Read the first PRT track CSV file found in *solver_output_dir*."""

        del model_name
        solver_output_dir = Path(solver_output_dir)
        csv_path = self._find_track_csv(solver_output_dir)
        if csv_path is None:
            logger.warning("No MODFLOW 6 PRT track CSV found in %s", solver_output_dir)
            return
        tdis_path = next(iter(solver_output_dir.glob("*.tdis")), solver_output_dir / "mfsim.tdis")
        self._extract_track_csv(
            sim_id,
            store,
            csv_path,
            time_units=read_time_units_from_tdis(tdis_path),
        )

    @staticmethod
    def _find_track_csv(solver_output_dir: Path) -> Path | None:
        patterns = ("*.trk.csv", "*track*.csv", "*.csv")
        seen: set[Path] = set()
        candidates: list[Path] = []
        for pattern in patterns:
            for path in sorted(solver_output_dir.glob(pattern)):
                if path in seen:
                    continue
                seen.add(path)
                name = path.name.lower()
                if "bud" in name or "budget" in name:
                    continue
                candidates.append(path)
        return candidates[0] if candidates else None

    def _extract_track_csv(
        self,
        sim_id: str,
        store: Any,
        csv_path: Path,
        *,
        time_units: str = "DAYS",
    ) -> None:
        arrays = read_prt_track_csv(csv_path, time_units=time_units)
        if arrays is None:
            logger.debug("Empty MODFLOW 6 PRT track CSV %s", csv_path)
            return

        sz = store.open_zarr(sim_id)
        try:
            particles_grp = sz.root.require_group("particles")
            for name, arr in [
                ("x", arrays.x),
                ("y", arrays.y),
                ("z", arrays.z),
                ("time", arrays.time),
            ]:
                particles_grp.create_array(name, data=arr, overwrite=True)
            if arrays.status is not None:
                particles_grp.create_array("status", data=arrays.status, overwrite=True)
            if arrays.reason is not None:
                particles_grp.create_array("reason", data=arrays.reason, overwrite=True)
            particles_grp.attrs["source_solver"] = self.solver_name
            particles_grp.attrs["source_file"] = csv_path.name
            particles_grp.attrs["source_time_units"] = arrays.source_time_units
            particles_grp.attrs["time_units"] = "days"
        finally:
            sz.close()

        logger.info(
            "Extracted %d MODFLOW 6 PRT particle tracks (max %d steps) for sim %s",
            arrays.n_particles,
            arrays.max_steps,
            sim_id,
        )

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None:
        """No derived variables for particle tracking yet."""
        del sim_id, store, config
