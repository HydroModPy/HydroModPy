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
        hdry: float = -100.0,
        hnoflo: float = -9999.0,
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

        # Write head fields — mask HDRY/HNOFLO sentinels to NaN so that
        # all downstream consumers (watertable, seepage, cross-section, etc.)
        # receive clean data without needing to re-detect sentinels.
        for t, time in enumerate(times):
            head = head_file.get_data(totim=time)
            # Reshape from (nlay, nrow, ncol) to (nlay, n_cells)
            values = head.reshape(nlay, n_cells).astype("float64")
            values[np.isclose(values, hdry, atol=1.0)] = np.nan
            values[np.isclose(values, hnoflo, atol=1.0)] = np.nan
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

        # Write surface elevation for derived variables.
        self._write_surface_elevation(sim_id, store, solver_output_dir, model_name, nlay, nrow, ncol)

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

        n_cells = nrow * ncol
        for t, (time, kstpkper) in enumerate(zip(times, kstpkpers)):
            for component in record_names:
                try:
                    # Use full3D=True to get 3D arrays for list-based
                    # packages (DRN, WEL, RCH, etc.) that otherwise
                    # return recarray objects.
                    data = cbb.get_data(
                        text=component, kstpkper=kstpkper, totim=time,
                        full3D=True,
                    )
                    if not data:
                        continue
                    arr = np.asarray(data[0], dtype="float64")
                    if arr.ndim >= 2:
                        flux_in = float(np.maximum(arr, 0).sum())
                        flux_out = float(np.minimum(arr, 0).sum())
                    else:
                        flux_in = 0.0
                        flux_out = 0.0
                    store.write_budget(
                        sim_id, t, 0, component.lower().strip(),
                        flux_in, abs(flux_out),
                    )
                    if spatial_fields and arr.ndim >= 2:
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

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: ResultStore,
        solver_output_dir: Path,
        model_name: str,
        nlay: int,
        nrow: int,
        ncol: int,
    ) -> None:
        """Write surface_top array from DIS file for derived variable computation."""
        try:
            import flopy
            import warnings

            nam_path = solver_output_dir / f"{model_name}.nam"
            n_cells = nrow * ncol

            if not nam_path.exists():
                return

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = flopy.modflow.Modflow.load(
                    str(nam_path), model_ws=str(solver_output_dir),
                    load_only=["DIS"], check=False, verbose=False,
                    exe_name="mfnwt",
                )
            top = np.asarray(m.dis.top.array, dtype="float64").ravel()[:n_cells]
            botm = np.asarray(m.dis.botm.array, dtype="float64")
            z_flat = np.concatenate([top[:1], botm[:, 0, 0]]) if botm.ndim == 3 else np.array([float(top[0]), float(top[0]) - 10.0])

            grp = store.open_zarr_group(sim_id)
            if "mesh" not in grp:
                grp.create_group("mesh")
            mesh = grp["mesh"]
            mesh.create_array("z_interfaces", data=z_flat, overwrite=True)
            mesh.create_array("surface_top", data=top, overwrite=True)
            mesh.attrs["n_cells"] = int(n_cells)
            mesh.attrs["n_layers"] = int(nlay)
        except Exception:
            logger.debug("Could not write surface elevation for sim %s", sim_id)

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
