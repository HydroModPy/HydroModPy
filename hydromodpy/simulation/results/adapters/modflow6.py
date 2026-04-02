"""Output adapter for MODFLOW 6 solver results."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hydromodpy.simulation.results.store import ResultStore

logger = logging.getLogger(__name__)


class Modflow6OutputAdapter:
    """Read MODFLOW 6 binary outputs and inject them into a ResultStore.

    Expects a solver output directory with ``{model_name}.hds`` and
    ``{model_name}.cbc`` in MODFLOW 6 format.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: ResultStore,
        *,
        model_name: str | None = None,
    ) -> None:
        """Read MF6 .hds and .cbc files and write into the store."""
        import flopy.utils.binaryfile as bf

        solver_output_dir = Path(solver_output_dir)
        if model_name is None:
            hds_files = list(solver_output_dir.glob("*.hds"))
            if not hds_files:
                raise FileNotFoundError(f"No .hds file in {solver_output_dir}")
            model_name = hds_files[0].stem

        hds_path = solver_output_dir / f"{model_name}.hds"
        cbc_path = solver_output_dir / f"{model_name}.cbc"

        head_file = bf.HeadFile(str(hds_path))
        times = head_file.get_times()
        kstpkpers = head_file.get_kstpkper()
        n_timesteps = len(times)

        head0 = head_file.get_data(totim=times[0])
        if head0.ndim == 3:
            nlay, nrow, ncol = head0.shape
            n_cells = nrow * ncol
        elif head0.ndim == 2:
            nlay = 1
            n_cells = head0.shape[-1]
        else:
            nlay = 1
            n_cells = head0.size

        logger.info(
            "Extracting MODFLOW 6 results: %d timesteps, %d layers, %d cells",
            n_timesteps, nlay, n_cells,
        )

        for t, time in enumerate(times):
            head = head_file.get_data(totim=time)
            values = head.reshape(nlay, n_cells) if head.ndim == 3 else head.reshape(nlay, n_cells)
            store.write_field(
                sim_id, "head", t, values,
                n_timesteps=n_timesteps if t == 0 else None,
            )

        if cbc_path.exists():
            self._extract_budget(sim_id, store, cbc_path, times, kstpkpers)

        head_file.close()

    def _extract_budget(
        self,
        sim_id: str,
        store: ResultStore,
        cbc_path: Path,
        times: list,
        kstpkpers: list,
    ) -> None:
        """Extract cell budget data from MF6 .cbc file."""
        import flopy.utils.binaryfile as bf

        cbb = bf.CellBudgetFile(str(cbc_path))
        record_names = [r.decode().strip() for r in cbb.get_unique_record_names()]

        for t, (time, kstpkper) in enumerate(zip(times, kstpkpers)):
            for component in record_names:
                try:
                    data = cbb.get_data(text=component, kstpkper=kstpkper, totim=time)
                    if not data:
                        continue
                    arr = data[0]
                    if hasattr(arr, "shape") and arr.ndim >= 1:
                        flux_in = float(np.maximum(arr, 0).sum())
                        flux_out = float(np.minimum(arr, 0).sum())
                    else:
                        flux_in = 0.0
                        flux_out = 0.0
                    store.write_budget(
                        sim_id, t, 0, component.lower().strip(),
                        flux_in, abs(flux_out),
                    )
                except Exception:
                    logger.debug("Could not read MF6 budget '%s' at t=%d", component, t)

        cbb.close()

    def derive(
        self,
        sim_id: str,
        store: ResultStore,
        config: dict | None = None,
    ) -> None:
        """Compute derived variables from stored head fields."""
        from hydromodpy.simulation.results.adapters.derived import compute_derived

        cfg = config or {}
        compute_derived(sim_id, store, cfg)
