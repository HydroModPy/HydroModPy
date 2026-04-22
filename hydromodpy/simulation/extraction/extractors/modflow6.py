"""Output adapter for MODFLOW 6 solver results."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from typing import Any

logger = logging.getLogger(__name__)


class Modflow6OutputAdapter:
    """Read MODFLOW 6 binary outputs and inject them into a SimulationCatalog.

    Expects a solver output directory with ``{model_name}.hds`` and
    ``{model_name}.cbc`` in MODFLOW 6 format.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        model_name: str | None = None,
        budget_spatial_fields: bool = False,
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
            values = values.astype("float64")
            # MF6 uses 1e30 for dry/no-flow cells.
            values[np.abs(values) > 1e20] = np.nan
            store.write_field(
                sim_id, "head", t, values,
                n_timesteps=n_timesteps if t == 0 else None,
            )

        if cbc_path.exists():
            self._extract_budget(
                sim_id, store, cbc_path, times, kstpkpers,
                spatial_fields=budget_spatial_fields,
                nlay=nlay,
                n_cells=n_cells,
            )

        lst_path = solver_output_dir / f"{model_name}.lst"
        if lst_path.exists():
            self._extract_mass_balance(sim_id, store, lst_path)

        head_file.close()

        # Write minimal mesh data (surface elevation) for derived variables.
        self._write_surface_elevation(sim_id, store, solver_output_dir, model_name, nlay, n_cells)

    def _extract_budget(
        self,
        sim_id: str,
        store: Any,
        cbc_path: Path,
        times: list,
        kstpkpers: list,
        *,
        spatial_fields: bool = False,
        nlay: int = 1,
        n_cells: int = 0,
    ) -> None:
        """Extract cell budget data from MF6 .cbc file."""
        import flopy.utils.binaryfile as bf

        try:
            cbb = bf.CellBudgetFile(str(cbc_path))
        except Exception:
            cbb = bf.CellBudgetFile(str(cbc_path), precision="double")
        record_names = [r.decode().strip() for r in cbb.get_unique_record_names()]

        budget_records: list[dict] = []
        for t, (time, kstpkper) in enumerate(zip(times, kstpkpers)):
            for component in record_names:
                try:
                    data = cbb.get_data(text=component, kstpkper=kstpkper, totim=time)
                except Exception as exc:
                    logger.debug(
                        "Could not read MF6 budget '%s' at t=%d: %s",
                        component, t, exc,
                    )
                    continue
                if not data:
                    continue
                arr = data[0]
                # MF6 stress packages (DRN, CHD, WEL, etc.) return
                # structured recarrays instead of plain ndarrays.
                # Convert to a full (nlay, n_cells) grid array.
                if hasattr(arr, "dtype") and arr.dtype.names is not None:
                    arr = self._recarray_to_grid(arr, nlay, n_cells)
                if hasattr(arr, "shape") and arr.ndim >= 1:
                    flux_in = float(np.maximum(arr, 0).sum())
                    flux_out = float(np.minimum(arr, 0).sum())
                else:
                    flux_in = 0.0
                    flux_out = 0.0
                budget_records.append({
                    "timestep": t,
                    "zone_id": "0",
                    "component": component.lower().strip(),
                    "flux_in": flux_in,
                    "flux_out": abs(flux_out),
                    "unit": "m3/d",
                })
                if spatial_fields and hasattr(arr, "shape") and arr.ndim >= 1:
                    # n_timesteps is always passed: the store ignores it
                    # on subsequent writes, but needs it for allocation
                    # on the first write — which may not be t=0 if the
                    # record is absent there (e.g. STORAGE in a steady
                    # initial stress period).
                    store.write_field(
                        sim_id, component.lower().strip(), t,
                        arr.reshape(-1) if arr.ndim == 1 else arr,
                        n_timesteps=len(times),
                        subgroup="budget",
                    )

        if budget_records:
            store.write_budgets(sim_id, budget_records)
        cbb.close()

    @staticmethod
    def _recarray_to_grid(
        rec: np.ndarray,
        nlay: int,
        n_cells: int,
    ) -> np.ndarray:
        """Convert a MF6 stress-package recarray to a full grid array.

        MF6 stress packages store sparse records with 1-based ``node``
        IDs and ``q`` flux values.  This scatters them into a dense
        ``(nlay, n_cells)`` array.
        """
        names = rec.dtype.names
        q = np.asarray(rec["q"] if "q" in names else rec[names[-1]], dtype="float64")

        if n_cells == 0:
            return q

        nodes = np.asarray(rec["node"], dtype="int64") if "node" in names else None
        out = np.zeros((nlay, n_cells), dtype="float64")
        if nodes is not None:
            idx = nodes - 1  # 1-based → 0-based
            lay = idx // n_cells
            cell = idx % n_cells
            valid = (lay >= 0) & (lay < nlay) & (cell >= 0) & (cell < n_cells)
            np.add.at(out, (lay[valid], cell[valid]), q[valid])
        else:
            n = min(len(q), n_cells)
            out[0, :n] = q[:n]
        return out

    def _extract_mass_balance(
        self,
        sim_id: str,
        store: Any,
        lst_path: Path,
    ) -> None:
        """Parse MODFLOW 6 listing file for mass balance summary.

        Uses ``flopy.utils.Mf6ListBudget`` to read volumetric budget
        from the listing file.
        """
        try:
            from flopy.utils import Mf6ListBudget

            mf6_list = Mf6ListBudget(str(lst_path))
            inc, cum = mf6_list.get_budget()
            if inc is not None:
                names = inc.dtype.names
                records = []
                for t in range(len(inc)):
                    total_in = float(inc[t]["TOTAL_IN"]) if "TOTAL_IN" in names else 0.0
                    total_out = float(inc[t]["TOTAL_OUT"]) if "TOTAL_OUT" in names else 0.0
                    pct_err = (
                        float(inc[t]["PERCENT_DISCREPANCY"])
                        if "PERCENT_DISCREPANCY" in names
                        else 0.0
                    )
                    records.append({
                        "timestep": t,
                        "total_in": total_in,
                        "total_out": total_out,
                        "storage_in": 0.0,
                        "storage_out": 0.0,
                        "percent_error": pct_err,
                    })
                store.write_mass_balances(sim_id, records)
        except Exception:
            logger.warning("Could not parse MF6 listing file %s", lst_path)

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        nlay: int,
        n_cells: int,
    ) -> None:
        """Write z_interfaces from grid data so derived variables can use them."""
        try:
            grb_files = list(solver_output_dir.glob("*.dis.grb")) + list(
                solver_output_dir.glob("*.disv.grb")
            )
            if grb_files:
                try:
                    from flopy.mf6.utils import MfGrdFile
                except ImportError:
                    from flopy.utils import MfGrdFile

                grd = MfGrdFile(str(grb_files[0]))
                top_raw = getattr(grd, "top1d", None) or getattr(grd, "top")
                bot_raw = getattr(grd, "bot1d", None) or getattr(grd, "bot")
                top = np.asarray(top_raw, dtype="float64").ravel()[:n_cells]
                botm = np.asarray(bot_raw, dtype="float64")
                botm_per_layer = botm.reshape(nlay, n_cells) if botm.size == nlay * n_cells else None
                if botm_per_layer is not None:
                    z_intf = np.vstack([top.reshape(1, -1), botm_per_layer])
                    z_flat = np.array([z_intf[:, 0].mean()])  # placeholder
                    z_flat = np.concatenate(
                        [top[:1], botm_per_layer[:, 0]]
                    )  # (nlay+1,)
                else:
                    z_flat = np.array([float(top.mean()), float(top.mean()) - 10.0])
            else:
                return  # no grid binary file

            grp = store.open_zarr_group(sim_id)
            if "mesh" not in grp:
                grp.create_group("mesh")
            mesh = grp["mesh"]
            mesh.create_array("z_interfaces", data=z_flat, overwrite=True)
            # Store the full top array so derived variables can use per-cell top.
            mesh.create_array("surface_top", data=top, overwrite=True)
            mesh.attrs["n_cells"] = int(n_cells)
            mesh.attrs["n_layers"] = int(nlay)
        except Exception:
            logger.debug("Could not write surface elevation for sim %s", sim_id, exc_info=True)

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None:
        """Compute derived variables from stored head fields."""
        from hydromodpy.simulation.extraction.extractors.derived import compute_derived

        cfg = config or {}
        compute_derived(sim_id, store, cfg)
