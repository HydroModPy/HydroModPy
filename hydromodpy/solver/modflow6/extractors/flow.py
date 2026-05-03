"""Output adapter for MODFLOW 6 flow solver results."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class Modflow6OutputAdapter:
    """Read MODFLOW 6 binary outputs and inject them into a SimulationCatalog.

    Expects a solver output directory with ``{model_name}.hds`` and
    ``{model_name}.cbc`` in MODFLOW 6 format.
    """

    solver_name = "modflow6"
    category = "distributed"

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
        grid_shape: tuple[int, int] | None = None
        if head0.ndim == 3:
            nlay, nrow, ncol = head0.shape
            n_cells = nrow * ncol
            grid_shape = (int(nrow), int(ncol))
        elif head0.ndim == 2:
            nlay = 1
            n_cells = int(head0.size)
            grid_shape = tuple(int(v) for v in head0.shape)
        else:
            nlay = 1
            n_cells = head0.size

        logger.info(
            "Extracting MODFLOW 6 results: %d timesteps, %d layers, %d cells",
            n_timesteps,
            nlay,
            n_cells,
        )

        for t, time in enumerate(times):
            head = head_file.get_data(totim=time)
            values = head.reshape(nlay, n_cells)
            values = values.astype("float64")
            values[np.abs(values) > 1e20] = np.nan
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
                spatial_fields=budget_spatial_fields,
                nlay=nlay,
                n_cells=n_cells,
            )

        lst_path = solver_output_dir / f"{model_name}.lst"
        if lst_path.exists():
            self._extract_mass_balance(sim_id, store, lst_path)

        head_file.close()

        self._write_surface_elevation(
            sim_id,
            store,
            solver_output_dir,
            model_name,
            nlay,
            n_cells,
            grid_shape=grid_shape,
        )

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
        for t, (time, kstpkper) in enumerate(zip(times, kstpkpers, strict=False)):
            for component in record_names:
                try:
                    data = cbb.get_data(text=component, kstpkper=kstpkper, totim=time)
                except Exception as exc:
                    logger.debug(
                        "Could not read MF6 budget '%s' at t=%d: %s",
                        component,
                        t,
                        exc,
                    )
                    continue
                if not data:
                    continue
                arr = data[0]
                if hasattr(arr, "dtype") and arr.dtype.names is not None:
                    arr = self._recarray_to_grid(arr, nlay, n_cells)
                if hasattr(arr, "shape") and arr.ndim >= 1:
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
                        # HydroModPy writes MODFLOW 6 TDIS in seconds and
                        # converts hydraulic inputs to SI before assembly.
                        "unit": "m3/s",
                    }
                )
                if spatial_fields and hasattr(arr, "shape") and arr.ndim >= 1:
                    if arr.size == nlay * n_cells:
                        field = arr.reshape(nlay, n_cells)
                    elif arr.ndim == 1 and arr.size == n_cells:
                        field = arr.reshape(1, n_cells)
                    else:
                        field = None
                    if field is not None:
                        try:
                            store.write_field(
                                sim_id,
                                component.lower().strip(),
                                t,
                                field,
                                n_timesteps=len(times),
                                subgroup="budget",
                            )
                        except Exception:
                            logger.debug(
                                "Skipped write_field for MF6 budget '%s' at t=%d",
                                component,
                                t,
                                exc_info=True,
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
            idx = nodes - 1
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
        """Parse MODFLOW 6 listing file for mass balance summary."""
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
                    records.append(
                        {
                            "timestep": t,
                            "total_in": total_in,
                            "total_out": total_out,
                            "storage_in": 0.0,
                            "storage_out": 0.0,
                            "percent_error": pct_err,
                        }
                    )
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
        *,
        grid_shape: tuple[int, int] | None = None,
    ) -> None:
        """Write mesh topology and surface elevation for derived variables."""
        try:
            grb_files = list(solver_output_dir.glob("*.dis.grb")) + list(
                solver_output_dir.glob("*.disv.grb")
            )
            grid_type = None
            vertices = None
            face_node_connectivity = None
            if grb_files:
                try:
                    from flopy.mf6.utils import MfGrdFile
                except ImportError:
                    from flopy.utils import MfGrdFile

                grd = MfGrdFile(str(grb_files[0]))
                grid_type = str(getattr(grd, "grid_type", "") or "").lower() or None
                top_raw = getattr(grd, "top1d", None)
                if top_raw is None:
                    top_raw = grd.top
                bot_raw = getattr(grd, "bot1d", None)
                if bot_raw is None:
                    bot_raw = grd.bot
                top = np.asarray(top_raw, dtype="float64").ravel()[:n_cells]
                botm = np.asarray(bot_raw, dtype="float64")
                botm_per_layer = (
                    botm.reshape(nlay, n_cells) if botm.size == nlay * n_cells else None
                )
                if botm_per_layer is not None:
                    z_intf = np.vstack([top.reshape(1, -1), botm_per_layer])
                    z_flat = np.array([z_intf[:, 0].mean()])
                    z_flat = np.concatenate([top[:1], botm_per_layer[:, 0]])
                else:
                    z_flat = np.array([float(top.mean()), float(top.mean()) - 10.0])
                geometry = self._mesh_geometry_from_grid(grd, n_cells=n_cells)
                if geometry is not None:
                    vertices, face_node_connectivity = geometry
            else:
                return

            if face_node_connectivity is None:
                geometry = self._structured_mesh_geometry_from_shape(
                    store,
                    sim_id,
                    n_cells=n_cells,
                    grid_shape=grid_shape,
                )
                if geometry is not None:
                    vertices, face_node_connectivity = geometry

            grp = store.open_zarr_group(sim_id)
            if "mesh" not in grp:
                grp.create_group("mesh")
            mesh = grp["mesh"]
            if vertices is not None and face_node_connectivity is not None:
                mesh.create_array("vertices", data=vertices.astype("float64"), overwrite=True)
                mesh.create_array(
                    "face_node_connectivity",
                    data=face_node_connectivity.astype("int32"),
                    overwrite=True,
                )
            mesh.create_array("z_interfaces", data=z_flat, overwrite=True)
            mesh.create_array("surface_top", data=top, overwrite=True)
            mesh.attrs["n_cells"] = int(n_cells)
            mesh.attrs["n_layers"] = int(nlay)
            if grid_type:
                mesh.attrs["grid_type"] = grid_type
            structured_shape = self._structured_shape_from_vertices(vertices, n_cells=n_cells)
            if (
                structured_shape is None
                and grid_shape is not None
                and int(grid_shape[0]) * int(grid_shape[1]) == int(n_cells)
            ):
                structured_shape = (int(grid_shape[0]), int(grid_shape[1]))
            if structured_shape is not None:
                mesh.attrs["structured_shape"] = [
                    int(structured_shape[0]),
                    int(structured_shape[1]),
                ]
        except Exception:
            logger.debug("Could not write surface elevation for sim %s", sim_id, exc_info=True)

    @staticmethod
    def _mesh_geometry_from_grid(
        grid: Any,
        *,
        n_cells: int,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Return UGRID vertices/connectivity from a FloPy MfGrdFile."""
        verts = getattr(grid, "verts", None)
        iverts = getattr(grid, "iverts", None)
        if verts is not None and iverts is not None:
            vertices = np.asarray(verts, dtype="float64")
            if vertices.ndim == 2 and vertices.shape[1] == 2:
                vertices = np.column_stack([vertices, np.zeros(vertices.shape[0], dtype="float64")])
            connectivity = Modflow6OutputAdapter._padded_face_connectivity(iverts, n_cells=n_cells)
            if connectivity is not None:
                return vertices, connectivity

        try:
            modelgrid = grid.modelgrid
            xvertices = np.asarray(modelgrid.xvertices, dtype="float64")
            yvertices = np.asarray(modelgrid.yvertices, dtype="float64")
        except Exception:
            return None

        if xvertices.ndim != 2 or yvertices.shape != xvertices.shape:
            return None
        nrow = int(xvertices.shape[0] - 1)
        ncol = int(xvertices.shape[1] - 1)
        if nrow <= 0 or ncol <= 0 or nrow * ncol != int(n_cells):
            return None
        vertices = np.column_stack(
            [
                xvertices.ravel(),
                yvertices.ravel(),
                np.zeros(xvertices.size, dtype="float64"),
            ]
        )
        face_node_connectivity = Modflow6OutputAdapter._structured_face_connectivity(nrow, ncol)
        return vertices, face_node_connectivity

    @staticmethod
    def _padded_face_connectivity(
        iverts: Any,
        *,
        n_cells: int,
    ) -> np.ndarray | None:
        """Convert ragged MF6 iverts lists to padded UGRID connectivity."""
        rows: list[list[int]] = []
        for row in list(iverts)[: int(n_cells)]:
            cleaned = [int(node) for node in row if int(node) >= 0]
            if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
                cleaned = cleaned[:-1]
            if len(cleaned) < 3:
                rows.append([])
            else:
                rows.append(cleaned)
        if len(rows) != int(n_cells) or not any(rows):
            return None
        width = max(len(row) for row in rows)
        connectivity = np.full((int(n_cells), width), -1, dtype="int32")
        for cell_id, row in enumerate(rows):
            if row:
                connectivity[cell_id, : len(row)] = row
        return connectivity

    @staticmethod
    def _structured_face_connectivity(nrow: int, ncol: int) -> np.ndarray:
        """Return quadrilateral face connectivity for a structured grid."""
        nc = int(ncol) + 1
        connectivity = np.empty((int(nrow) * int(ncol), 4), dtype="int32")
        for row in range(int(nrow)):
            for col in range(int(ncol)):
                cell_id = row * int(ncol) + col
                node_id = row * nc + col
                connectivity[cell_id] = (
                    node_id,
                    node_id + 1,
                    node_id + nc + 1,
                    node_id + nc,
                )
        return connectivity

    @staticmethod
    def _structured_shape_from_vertices(
        vertices: np.ndarray | None,
        *,
        n_cells: int,
    ) -> tuple[int, int] | None:
        """Infer a regular grid shape from rectangular UGRID vertices."""
        if vertices is None:
            return None
        values = np.asarray(vertices, dtype="float64")
        if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] < 2:
            return None
        unique_x = np.unique(np.round(values[:, 0], decimals=9))
        unique_y = np.unique(np.round(values[:, 1], decimals=9))
        ncol = int(unique_x.size - 1)
        nrow = int(unique_y.size - 1)
        if nrow > 0 and ncol > 0 and nrow * ncol == int(n_cells):
            return nrow, ncol
        return None

    @staticmethod
    def _structured_mesh_geometry_from_shape(
        store: Any,
        sim_id: str,
        *,
        n_cells: int,
        grid_shape: tuple[int, int] | None,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Build rectangular UGRID geometry when the GRB lacks vertices."""
        shape = grid_shape
        if shape is None or int(shape[0]) * int(shape[1]) != int(n_cells):
            side = int(np.sqrt(int(n_cells)))
            shape = (side, side) if side * side == int(n_cells) else None
        if shape is None:
            return None

        nrow, ncol = int(shape[0]), int(shape[1])
        try:
            sz = store.open_zarr(sim_id)
            try:
                _, meta = sz.read_geographic_raster("watershed_dem")
            finally:
                sz.close()
            transform = meta["transform"]
            geographic_metadata = store.read_geographic_metadata(sim_id)
            geo_rows = int(geographic_metadata.get("nrow", nrow))
            geo_cols = int(geographic_metadata.get("ncol", ncol))
            xmin = float(transform[2])
            xmax = xmin + geo_cols * float(transform[0])
            ymax = float(transform[5])
            ymin = ymax + geo_rows * float(transform[4])
        except Exception:
            xmin, xmax = 0.0, float(ncol)
            ymin, ymax = 0.0, float(nrow)

        x_edges = np.linspace(xmin, xmax, ncol + 1, dtype="float64")
        y_edges = np.linspace(ymax, ymin, nrow + 1, dtype="float64")
        xx, yy = np.meshgrid(x_edges, y_edges)
        vertices = np.column_stack(
            [
                xx.ravel(),
                yy.ravel(),
                np.zeros(xx.size, dtype="float64"),
            ]
        )
        return vertices, Modflow6OutputAdapter._structured_face_connectivity(nrow, ncol)

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
