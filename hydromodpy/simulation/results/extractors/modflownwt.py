"""Output adapter for MODFLOW-NWT solver results."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from hydromodpy.results.store import ResultStore

logger = logging.getLogger(__name__)


class ModflowNwtOutputAdapter:
    """Read MODFLOW-NWT binary outputs and inject them into a ResultStore.

    Expects a solver output directory containing ``{model_name}.hds``,
    ``{model_name}.cbc``, and optionally ``{model_name}.lst``.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: ResultStore,
        *,
        model_name: str | None = None,
        budget_spatial_fields: bool = False,
    ) -> None:
        """Read .hds and .cbc files and write fields into the store."""
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

        # Read head for first timestep to get grid dimensions
        head0 = head_file.get_data(totim=times[0])
        nlay, nrow, ncol = head0.shape
        n_cells = nrow * ncol

        logger.info(
            "Extracting MODFLOW-NWT results: %d timesteps, %d layers, %d cells",
            n_timesteps, nlay, n_cells,
        )

        # Write head fields
        for t, time in enumerate(times):
            head = head_file.get_data(totim=time)
            # Reshape from (nlay, nrow, ncol) to (nlay, n_cells)
            values = head.reshape(nlay, n_cells)
            store.write_field(
                sim_id, "head", t, values,
                n_timesteps=n_timesteps if t == 0 else None,
            )

        # Write budget components
        if cbc_path.exists():
            self._extract_budget(
                sim_id, store, cbc_path, times, kstpkpers,
                nlay, nrow, ncol,
                spatial_fields=budget_spatial_fields,
            )

        # Write mass balance from listing file
        lst_path = solver_output_dir / f"{model_name}.lst"
        if lst_path.exists():
            self._extract_mass_balance(sim_id, store, lst_path)

        head_file.close()

    def _extract_budget(
        self,
        sim_id: str,
        store: ResultStore,
        cbc_path: Path,
        times: list,
        kstpkpers: list,
        nlay: int,
        nrow: int,
        ncol: int,
        *,
        spatial_fields: bool = False,
    ) -> None:
        """Extract cell budget data from .cbc file."""
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
                    if hasattr(arr, "shape") and arr.ndim >= 2:
                        flux_in = float(np.maximum(arr, 0).sum())
                        flux_out = float(np.minimum(arr, 0).sum())
                    else:
                        flux_in = 0.0
                        flux_out = 0.0
                    store.write_budget(
                        sim_id, t, 0, component.lower().strip(),
                        flux_in, abs(flux_out),
                    )
                    if spatial_fields and hasattr(arr, "shape") and arr.ndim >= 2:
                        n_cells = nrow * ncol
                        field = arr.reshape(nlay, n_cells) if arr.ndim == 3 else arr.reshape(1, n_cells)
                        store.write_field(
                            sim_id, component.lower().strip(), t, field,
                            n_timesteps=len(times) if t == 0 else None,
                            subgroup="budget",
                        )
                except Exception:
                    logger.debug("Could not read budget component '%s' at t=%d", component, t)

        cbb.close()

    def _extract_mass_balance(
        self,
        sim_id: str,
        store: ResultStore,
        lst_path: Path,
    ) -> None:
        """Parse MODFLOW listing file for mass balance summary."""
        try:
            from flopy.utils import MfListBudget
            mf_list = MfListBudget(str(lst_path))
            inc, cum = mf_list.get_budget_from_list()
            if inc is not None:
                for t in range(len(inc)):
                    total_in = float(inc[t]["IN-OUT"])
                    total_out = 0.0
                    pct_err = float(inc[t]["PERCENT_DISCREPANCY"]) if "PERCENT_DISCREPANCY" in inc.dtype.names else 0.0
                    store.write_mass_balance(sim_id, t, total_in, total_out, pct_err)
        except Exception:
            logger.debug("Could not parse listing file %s", lst_path)

    def derive(
        self,
        sim_id: str,
        store: ResultStore,
        config: dict | None = None,
    ) -> None:
        """Compute derived variables from stored head fields.

        Delegates to :mod:`hydromodpy.simulation.results.extractors.derived`.
        """
        from hydromodpy.simulation.results.extractors.derived import compute_derived

        cfg = config or {}
        compute_derived(sim_id, store, cfg)
