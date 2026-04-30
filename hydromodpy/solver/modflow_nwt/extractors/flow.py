"""Output adapter for MODFLOW-NWT flow solver results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

# Map MODFLOW ITMUNI codes to the canonical volumetric-flux unit label
# the extractor writes to the catalog. Codes follow the MODFLOW
# discretization-package convention (0 = undefined, 1 = seconds, …).
_ITMUNI_FLUX_UNIT: dict[int, str] = {
    0: "m3/s",
    1: "m3/s",
    2: "m3/min",
    3: "m3/h",
    4: "m3/d",
    5: "m3/yr",
}
_ITMUNI_SECONDS: dict[int, float] = {
    0: 1.0,
    1: 1.0,
    2: 60.0,
    3: 3600.0,
    4: 86400.0,
    5: 31557600.0,
}


def _read_itmuni(dis_path: Path) -> int:
    """Return the ITMUNI integer declared in a MODFLOW DIS file.

    The DIS header is two free-format integer lines: the first carries
    NLAY/NROW/NCOL/NPER, the second NSTP-related and ITMUNI/LENUNI. We
    parse only what we need and fall back to ``1`` (seconds) when the
    file is missing or malformed.
    """
    if not dis_path.is_file():
        return 1
    try:
        with dis_path.open("r", encoding="utf-8") as fh:
            header_lines: list[str] = []
            for raw in fh:
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                header_lines.append(stripped)
                if len(header_lines) >= 2:
                    break
        if len(header_lines) < 2:
            return 1
        tokens = header_lines[1].split()
        # Layout: NSTP_or_dummy ITMUNI LENUNI ... (free format).
        if len(tokens) >= 2:
            return int(tokens[1])
    except (OSError, ValueError):
        return 1
    return 1


def _flux_unit_for(itmuni: int) -> str:
    """Return the volumetric-flux unit label matching ``itmuni``."""
    return _ITMUNI_FLUX_UNIT.get(itmuni, "m3/s")


def _write_time_coordinate(store: Any, sim_id: str, times: list[float], itmuni: int) -> None:
    """Persist solver times as CF seconds since epoch."""
    writer = getattr(store, "write_time", None)
    if writer is None:
        raise TypeError("Simulation store must implement write_time().")
    factor = _ITMUNI_SECONDS.get(itmuni, 1.0)
    values = np.rint(np.asarray(times, dtype=float) * factor).astype("int64")
    writer(sim_id, values)


def _budget_key(name: str) -> str:
    """Normalize a MODFLOW listing budget column name."""
    return str(name).upper().replace("-", "_").replace(" ", "_")


def _budget_field_lookup(names: tuple[str, ...]) -> dict[str, str]:
    """Map normalized listing field names to their native dtype names."""
    return {_budget_key(name): name for name in names}


def _budget_value(row: np.void, fields: dict[str, str], *candidates: str) -> float:
    """Return a listing-budget value or NaN when the field is absent."""
    for candidate in candidates:
        native = fields.get(_budget_key(candidate))
        if native is not None:
            return float(row[native])
    return float("nan")


class ModflowNwtOutputAdapter:
    """Read MODFLOW-NWT binary outputs and inject them into a SimulationCatalog.

    Expects a solver output directory containing ``{model_name}.hds``,
    ``{model_name}.cbc``, and optionally ``{model_name}.lst``.
    """

    solver_name = "modflownwt"
    category = "distributed"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
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
        itmuni = _read_itmuni(solver_output_dir / f"{model_name}.dis")
        _write_time_coordinate(store, sim_id, times, itmuni)

        head0 = head_file.get_data(totim=times[0])
        nlay, nrow, ncol = head0.shape
        n_cells = nrow * ncol

        logger.info(
            "Extracting MODFLOW-NWT results: %d timesteps, %d layers, %d cells",
            n_timesteps,
            nlay,
            n_cells,
        )

        # Mask HDRY/HNOFLO sentinels to NaN so all downstream consumers
        # (watertable, seepage, cross-section, etc.) receive clean data.
        for t, time in enumerate(times):
            head = head_file.get_data(totim=time)
            values = head.reshape(nlay, n_cells).astype("float64")
            values[np.isclose(values, hdry, atol=1.0)] = np.nan
            values[np.isclose(values, hnoflo, atol=1.0)] = np.nan
            store.write_field(
                sim_id,
                "head",
                t,
                values,
                n_timesteps=n_timesteps if t == 0 else None,
            )

        if cbc_path.exists():
            self._extract_budget(
                sim_id,
                store,
                cbc_path,
                times,
                kstpkpers,
                nlay,
                nrow,
                ncol,
                spatial_fields=budget_spatial_fields,
                flux_unit=_flux_unit_for(itmuni),
            )

        lst_path = solver_output_dir / f"{model_name}.lst"
        if lst_path.exists():
            self._extract_mass_balance(sim_id, store, lst_path)

        head_file.close()

        self._write_surface_elevation(
            sim_id, store, solver_output_dir, model_name, nlay, nrow, ncol
        )

    def _extract_budget(
        self,
        sim_id: str,
        store: Any,
        cbc_path: Path,
        times: list,
        kstpkpers: list,
        nlay: int,
        nrow: int,
        ncol: int,
        *,
        spatial_fields: bool = False,
        flux_unit: str = "m3/s",
    ) -> None:
        """Extract cell budget data from .cbc file."""
        import flopy.utils.binaryfile as bf

        cbb = bf.CellBudgetFile(str(cbc_path))
        record_names = [r.decode().strip() for r in cbb.get_unique_record_names()]

        n_cells = nrow * ncol
        budget_records: list[dict] = []
        for t, (time, kstpkper) in enumerate(zip(times, kstpkpers, strict=False)):
            for component in record_names:
                try:
                    data = cbb.get_data(
                        text=component,
                        kstpkper=kstpkper,
                        totim=time,
                        full3D=True,
                    )
                except Exception as exc:
                    logger.debug(
                        "Could not read budget component '%s' at t=%d: %s",
                        component,
                        t,
                        exc,
                    )
                    continue
                if not data:
                    continue
                arr = np.asarray(data[0], dtype="float64")
                if arr.ndim >= 2:
                    flux_in = float(np.maximum(arr, 0).sum())
                    flux_out = float(np.minimum(arr, 0).sum())
                else:
                    flux_in = 0.0
                    flux_out = 0.0
                budget_records.append(
                    {
                        "timestep": t,
                        "zone_id": "0",
                        "component": component.lower().strip(),
                        "flux_in": flux_in,
                        "flux_out": abs(flux_out),
                        "unit": flux_unit,
                    }
                )
                if spatial_fields and arr.ndim >= 2:
                    field = arr.reshape(nlay, n_cells) if arr.ndim == 3 else arr.reshape(1, n_cells)
                    store.write_field(
                        sim_id,
                        component.lower().strip(),
                        t,
                        field,
                        n_timesteps=len(times),
                        subgroup="budget",
                    )

        if budget_records:
            store.write_budgets(sim_id, budget_records)
        cbb.close()

    def _extract_mass_balance(
        self,
        sim_id: str,
        store: Any,
        lst_path: Path,
    ) -> None:
        """Parse MODFLOW listing file for mass balance summary."""
        try:
            from flopy.utils import MfListBudget

            mf_list = MfListBudget(str(lst_path))
            inc, cum = mf_list.get_budget_from_list()
            del cum
            if inc is not None:
                records = []
                fields = _budget_field_lookup(inc.dtype.names or ())
                for t in range(len(inc)):
                    row = inc[t]
                    total_in = _budget_value(row, fields, "TOTAL_IN", "TOTAL IN")
                    total_out = _budget_value(row, fields, "TOTAL_OUT", "TOTAL OUT")
                    storage_in = _budget_value(row, fields, "STORAGE_IN", "STORAGE IN")
                    storage_out = _budget_value(row, fields, "STORAGE_OUT", "STORAGE OUT")
                    pct_err = _budget_value(
                        row,
                        fields,
                        "PERCENT_DISCREPANCY",
                        "PERCENT DISCREPANCY",
                    )
                    records.append(
                        {
                            "timestep": t,
                            "total_in": total_in,
                            "total_out": total_out,
                            "storage_in": storage_in,
                            "storage_out": storage_out,
                            "percent_error": pct_err,
                        }
                    )
                store.write_mass_balances(sim_id, records)
        except Exception:
            logger.warning("Could not parse listing file %s", lst_path, exc_info=True)

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        nlay: int,
        nrow: int,
        ncol: int,
    ) -> None:
        """Write surface_top array from DIS file for derived variable computation."""
        try:
            import warnings

            import flopy

            nam_path = solver_output_dir / f"{model_name}.nam"
            n_cells = nrow * ncol

            if not nam_path.exists():
                return

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = flopy.modflow.Modflow.load(
                    str(nam_path),
                    model_ws=str(solver_output_dir),
                    load_only=["DIS"],
                    check=False,
                    verbose=False,
                    exe_name="mfnwt",
                )
            top = np.asarray(m.dis.top.array, dtype="float64").ravel()[:n_cells]
            botm = np.asarray(m.dis.botm.array, dtype="float64")
            z_flat = (
                np.concatenate([top[:1], botm[:, 0, 0]])
                if botm.ndim == 3
                else np.array([float(top[0]), float(top[0]) - 10.0])
            )

            # Synthesize UGRID (vertices + face_node_connectivity) from the
            # structured DIS grid so downstream readers (piezometric_map,
            # exporters) can treat NWT runs the same way as DISV.
            sg = m.modelgrid
            x_edges = np.asarray(sg.xvertices, dtype="float64")
            y_edges = np.asarray(sg.yvertices, dtype="float64")
            vertices = np.column_stack(
                [
                    x_edges.ravel(),
                    y_edges.ravel(),
                    np.zeros(x_edges.size, dtype="float64"),
                ]
            )
            nc = ncol + 1
            fnc = np.empty((nrow * ncol, 4), dtype="int32")
            for r in range(nrow):
                for c in range(ncol):
                    i = r * ncol + c
                    n0 = r * nc + c
                    fnc[i] = (n0, n0 + 1, n0 + nc + 1, n0 + nc)

            grp = store._open_zarr_group(sim_id)
            if "mesh" not in grp:
                grp.create_group("mesh")
            mesh = grp["mesh"]
            mesh.create_array("vertices", data=vertices, overwrite=True)
            mesh.create_array("face_node_connectivity", data=fnc, overwrite=True)
            mesh.create_array("z_interfaces", data=z_flat, overwrite=True)
            mesh.create_array("surface_top", data=top, overwrite=True)
            mesh.attrs["n_cells"] = int(n_cells)
            mesh.attrs["n_layers"] = int(nlay)
        except Exception:
            logger.debug("Could not write surface elevation for sim %s", sim_id)

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
