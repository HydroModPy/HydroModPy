"""Output adapter for MT3DMS / MF6-GWT solver results."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hydromodpy.results.store import ResultStore

logger = logging.getLogger(__name__)


class Mt3dmsOutputAdapter:
    """Read MT3DMS / MF6-GWT binary outputs and inject them into a ResultStore.

    Expects a solver output directory containing ``{model_name}.ucn``
    (unformatted concentration file).
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: ResultStore,
        *,
        model_name: str | None = None,
    ) -> None:
        """Read .ucn file and write concentration fields into the store."""
        from flopy.utils import UcnFile

        solver_output_dir = Path(solver_output_dir)
        if model_name is None:
            ucn_files = list(solver_output_dir.glob("*.ucn"))
            if not ucn_files:
                raise FileNotFoundError(f"No .ucn file in {solver_output_dir}")
            model_name = ucn_files[0].stem

        ucn_path = solver_output_dir / f"{model_name}.ucn"
        ucn = UcnFile(str(ucn_path))
        times = ucn.get_times()
        n_timesteps = len(times)

        conc0 = ucn.get_data(totim=times[0])
        if conc0.ndim == 3:
            nlay, nrow, ncol = conc0.shape
            n_cells = nrow * ncol
        elif conc0.ndim == 2:
            nlay = 1
            n_cells = conc0.shape[-1]
        else:
            nlay = 1
            n_cells = conc0.size

        logger.info(
            "Extracting MT3DMS concentration: %d timesteps, %d layers, %d cells",
            n_timesteps, nlay, n_cells,
        )

        for t, time in enumerate(times):
            conc = ucn.get_data(totim=time)
            values = conc.reshape(nlay, n_cells)
            store.write_field(
                sim_id, "concentration", t, values,
                n_timesteps=n_timesteps if t == 0 else None,
            )

        ucn.close()

    def derive(
        self,
        sim_id: str,
        store: ResultStore,
        config: dict | None = None,
    ) -> None:
        """Compute derived variables from stored concentration fields.

        Delegates to :mod:`hydromodpy.simulation.results.extractors.derived`
        for transport-dependent variables (concentration_seepage,
        mass_seepage, mass_accumulated).
        """
        from hydromodpy.simulation.results.extractors.derived import compute_derived

        cfg = config or {}
        compute_derived(sim_id, store, cfg)
