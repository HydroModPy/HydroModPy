"""Per-timestep post-processing helpers for MODFLOW 6 flow and transport."""

from __future__ import annotations

import csv
import os
from collections.abc import Mapping
from typing import Protocol

import flopy.utils.binaryfile as bf
import numpy as np
import rasterio
from flopy.utils import postprocessing as pp

from hydromodpy.core.io import raster_io
from hydromodpy.core.logging import get_logger
from hydromodpy.core.tools import filesystem
from hydromodpy.solver.modflow_common import masstransfer
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions

from .diagnostics import RuntimeSupportOverviewModel, export_runtime_support_overview

logger = get_logger(__name__)

NODATA = -9999


class BudgetReaderLike(Protocol):
	"""Minimal MF6 budget-reader contract consumed by helper functions."""

	def get_data(self, *, kstpkper: tuple[int, int], text: str): ...


class SolverMeshLike(Protocol):
	"""Minimal solver-mesh contract consumed by MF6 post-processing helpers."""

	is_structured: bool
	top: np.ndarray
	planar_mesh: object
	n_cells: int

	def reshape_to_grid(self, flat_array: np.ndarray) -> np.ndarray: ...

	def flatten_from_grid(self, values: np.ndarray) -> np.ndarray: ...

	def cell_centroids(self) -> object: ...


class RoutingContextLike(Protocol):
	"""Minimal routing-context contract for raster accumulation exports."""

	correc_path: str
	direc_path: str


class FlowPostprocessModel(RuntimeSupportOverviewModel, Protocol):
	"""Minimal MODFLOW-6 contract consumed by flow post-processing exports."""

	full_path: str
	model_name: str
	save_file: str
	tifs_file: str
	times: list[float] | tuple[float, ...]
	ncpl: int
	nper: int
	nrow: int
	ncol: int
	dem: np.ndarray
	dem_mask: np.ndarray
	dem_watershed_path: str
	geographic: object
	solver_mesh: SolverMeshLike

	def _to_export_array(self, flat_array: np.ndarray) -> np.ndarray: ...

	def _ensure_solver_routing_context(self) -> RoutingContextLike: ...


class TransportPostprocessModel(Protocol):
	"""Minimal MODFLOW transport contract consumed by GWT post-processing."""

	full_path: str
	model_name_mt: str
	save_file: str
	tifs_file: str
	model_modflow: FlowPostprocessModel

	def _resolve_postprocess_options(
		self,
		*,
		export_all_tif: bool,
		options: ModflowPostprocessOptions | None,
	) -> ModflowPostprocessOptions: ...


def get_budget_records_or_none(
	cbb: BudgetReaderLike,
	*,
	kstpkper: tuple[int, int],
	text: str,
):
	"""Return one budget term, or None when the term is absent from the file."""
	try:
		return cbb.get_data(kstpkper=kstpkper, text=text)
	except Exception as exc:
		message = str(exc)
		if "text string is not in the budget file" in message.lower():
			return None
		raise


def open_budget_file(path: str):
	"""Open one MF6 cell-budget file with a small precision fallback chain."""
	for kwargs in ({}, {"precision": "double"}, {"precision": "single"}):
		try:
			return bf.CellBudgetFile(path, **kwargs)
		except TypeError:
			if kwargs:
				continue
			raise
		except Exception:
			if kwargs == {"precision": "single"}:
				raise
			continue


def compute_watertable_elevation(head: np.ndarray) -> np.ndarray:
	"""Extract the top water table as one flat `(ncpl,)` array."""
	wt = pp.get_water_table(head, NODATA)
	wt = np.asarray(wt, dtype=float).reshape(-1)
	wt[np.isnan(wt)] = NODATA
	wt[wt <= -1e20] = NODATA
	return wt


def compute_watertable_depth(
	*,
	watertable_elevation: np.ndarray,
	dem: np.ndarray,
	dem_mask: np.ndarray,
) -> np.ndarray:
	"""Compute depth to the water table on the solver cells."""
	return np.where(
		np.asarray(dem_mask, dtype=bool).reshape(-1),
		float(NODATA),
		np.maximum(
			np.asarray(dem, dtype=float).reshape(-1)
			- np.asarray(watertable_elevation, dtype=float).reshape(-1),
			0.0,
		),
	)


def compute_drain_outflow_and_seepage(
	drain_records,
	*,
	ncpl: int,
) -> tuple[np.ndarray, np.ndarray]:
	"""Map MF6 DRN records to per-cell outflow and seepage flags."""
	outflow = np.zeros(int(ncpl), dtype=float)
	seepage = np.zeros(int(ncpl), dtype=float)
	if drain_records is None or len(drain_records) == 0:
		return outflow, seepage

	record = drain_records[0]
	try:
		if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
			node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
			q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
			iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
		else:
			iterator = ((int(item[0]), float(item[-1])) for item in record)
		for node, q in iterator:
			if node <= 0:
				continue
			layer = (node - 1) // int(ncpl)
			cell_id = (node - 1) % int(ncpl)
			if layer == 0:
				outflow[cell_id] += max(-q, 0.0)
				seepage[cell_id] = 1.0 if q < 0 else seepage[cell_id]
	except Exception:
		return np.zeros(int(ncpl), dtype=float), np.zeros(int(ncpl), dtype=float)
	return outflow, seepage


def build_unstructured_cell_adjacency(model: FlowPostprocessModel) -> list[set[int]]:
	"""Return cell-to-cell adjacency for one unstructured planar mesh."""
	n_cells = int(getattr(model, "ncpl", 0) or getattr(model.solver_mesh, "n_cells", 0))
	adjacency = [set() for _ in range(n_cells)]
	support = getattr(model, "runtime_mesh_support", None)
	if support is not None:
		edge_cell_a = np.asarray(getattr(support, "edge_cell_a", ()), dtype=int).reshape(-1)
		edge_cell_b = np.asarray(getattr(support, "edge_cell_b", ()), dtype=int).reshape(-1)
		for cell_a, cell_b in zip(edge_cell_a.tolist(), edge_cell_b.tolist(), strict=False):
			if int(cell_a) < 0 or int(cell_b) < 0:
				continue
			if int(cell_a) >= n_cells or int(cell_b) >= n_cells:
				continue
			adjacency[int(cell_a)].add(int(cell_b))
			adjacency[int(cell_b)].add(int(cell_a))
		if any(neighbors for neighbors in adjacency):
			return adjacency

	planar_mesh = getattr(model.solver_mesh, "planar_mesh", None)
	if planar_mesh is None:
		return adjacency

	edge_owner: dict[tuple[int, int], int] = {}
	cell_offset = 0
	for block in tuple(getattr(planar_mesh, "cell_blocks", ()) or ()):
		connectivity = np.asarray(getattr(block, "connectivity", ()), dtype=int)
		if connectivity.ndim != 2:
			continue
		for local_index, node_ids in enumerate(connectivity.tolist()):
			cell_id = int(cell_offset + local_index)
			if cell_id >= n_cells:
				break
			nodes = np.asarray(node_ids, dtype=int).reshape(-1)
			if nodes.size < 3:
				continue
			for node_index in range(int(nodes.size)):
				node_a = int(nodes[node_index])
				node_b = int(nodes[(node_index + 1) % int(nodes.size)])
				edge = tuple(sorted((node_a, node_b)))
				owner = edge_owner.get(edge)
				if owner is None:
					edge_owner[edge] = cell_id
					continue
				if int(owner) == cell_id:
					continue
				adjacency[cell_id].add(int(owner))
				adjacency[int(owner)].add(cell_id)
		cell_offset += int(connectivity.shape[0])
	return adjacency


def accumulate_unstructured_cell_values(
	model: FlowPostprocessModel,
	*,
	local_values: np.ndarray,
	reference_values: np.ndarray,
	inactive_mask: np.ndarray | None = None,
) -> np.ndarray:
	"""Accumulate one per-cell source field along a downhill mesh graph."""
	local = np.asarray(local_values, dtype=float).reshape(-1)
	reference = np.asarray(reference_values, dtype=float).reshape(-1)
	n_cells = int(getattr(model, "ncpl", 0) or getattr(model.solver_mesh, "n_cells", 0))
	if local.size != n_cells or reference.size != n_cells:
		raise ValueError(
			"Unstructured accumulation requires local_values/reference_values "
			f"with {n_cells} entries."
		)

	if inactive_mask is None:
		mask = np.zeros(n_cells, dtype=bool)
	else:
		mask = np.asarray(inactive_mask, dtype=bool).reshape(-1)
		if mask.size != n_cells:
			raise ValueError(f"inactive_mask must have {n_cells} entries, got {mask.size}.")

	active = (~mask) & np.isfinite(reference)
	if not np.any(active):
		return np.zeros(n_cells, dtype=float)

	adjacency = build_unstructured_cell_adjacency(model)
	centroids = None
	try:
		centroids = np.asarray(model.solver_mesh.cell_centroids(), dtype=float).reshape(n_cells, 2)
	except Exception:
		centroids = None

	ref_active = reference[active]
	ref_range = float(np.nanmax(ref_active) - np.nanmin(ref_active)) if ref_active.size > 0 else 0.0
	tolerance = max(1.0e-9, 1.0e-9 * max(abs(ref_range), 1.0))
	downstream = np.full(n_cells, -1, dtype=int)

	for cell_id in np.flatnonzero(active).tolist():
		best_neighbor = -1
		best_score = 0.0
		cell_ref = float(reference[cell_id])
		for neighbor in adjacency[int(cell_id)]:
			if neighbor < 0 or neighbor >= n_cells or not bool(active[neighbor]):
				continue
			neighbor_ref = float(reference[int(neighbor)])
			drop = cell_ref - neighbor_ref
			if not np.isfinite(drop) or drop <= tolerance:
				continue
			score = drop
			if centroids is not None:
				delta_x = float(centroids[cell_id, 0] - centroids[int(neighbor), 0])
				delta_y = float(centroids[cell_id, 1] - centroids[int(neighbor), 1])
				distance = max((delta_x * delta_x + delta_y * delta_y) ** 0.5, 1.0e-12)
				score = drop / distance
			if score > best_score:
				best_score = float(score)
				best_neighbor = int(neighbor)
		downstream[int(cell_id)] = int(best_neighbor)

	clean_local = np.where(
		active & np.isfinite(local) & (local > float(NODATA)),
		np.maximum(local, 0.0),
		0.0,
	)
	accumulated = np.zeros(n_cells, dtype=float)
	order = np.argsort(np.where(active, reference, -np.inf).astype(float, copy=False))[::-1]
	for cell_id in order.tolist():
		if not bool(active[int(cell_id)]):
			continue
		accumulated[int(cell_id)] += float(clean_local[int(cell_id)])
		target = int(downstream[int(cell_id)])
		if target >= 0:
			accumulated[target] += float(accumulated[int(cell_id)])

	accumulated[~active] = np.nan
	return accumulated


def native_mesh_exports_enabled(options: ModflowPostprocessOptions) -> bool:
	"""Return True when one native mesh export format is enabled."""
	return bool(
		getattr(options, "native_mesh_npz", False)
		or getattr(options, "native_mesh_csv", False)
		or getattr(options, "native_mesh_vtu", False)
		or getattr(options, "native_mesh_png", False)
	)


def native_cell_series_payload(
	model: FlowPostprocessModel,
	*,
	datasets: Mapping[str, Mapping[int, np.ndarray]],
) -> dict[str, np.ndarray]:
	"""Normalize time-indexed cell datasets to stacked `(ntime, ncpl)` arrays."""
	payload: dict[str, np.ndarray] = {}
	for name, data_by_time in datasets.items():
		if not data_by_time:
			continue
		stacked_rows: list[np.ndarray] = []
		for _, values in sorted(data_by_time.items(), key=lambda item: int(item[0])):
			flat = np.asarray(
				model.solver_mesh.flatten_from_grid(np.asarray(values)),
				dtype=float,
			).reshape(-1)
			if flat.size != int(model.ncpl):
				continue
			stacked_rows.append(flat)
		if stacked_rows:
			payload[str(name)] = np.vstack(stacked_rows).astype(float, copy=False)
	return payload


def export_native_mesh_outputs(
	model: FlowPostprocessModel,
	*,
	options: ModflowPostprocessOptions,
	times: list[float] | tuple[float, ...],
	datasets: Mapping[str, Mapping[int, np.ndarray]],
	prefix: str,
) -> None:
	"""Write native mesh exports (NPZ, CSV, VTU, PNG) for cell-based outputs."""
	if not native_mesh_exports_enabled(options):
		return

	cell_series = native_cell_series_payload(model, datasets=datasets)
	if not cell_series:
		return

	mesh_dir = os.path.join(model.save_file, "_mesh")
	filesystem.create_folder(mesh_dir)
	time_index = np.arange(len(times), dtype=int)
	times_array = np.asarray(times, dtype=float)
	cell_ids = np.arange(int(model.ncpl), dtype=int)

	if getattr(options, "native_mesh_npz", False):
		for name, values in cell_series.items():
			np.savez_compressed(
				os.path.join(mesh_dir, f"{prefix}_{name}.npz"),
				time_index=time_index,
				times=times_array,
				cell_ids=cell_ids,
				values=values,
			)

	if getattr(options, "native_mesh_csv", False):
		for name, values in cell_series.items():
			csv_path = os.path.join(mesh_dir, f"{prefix}_{name}.csv")
			with open(csv_path, "w", encoding="utf-8", newline="") as stream:
				writer = csv.writer(stream)
				writer.writerow(["time_index", "time", "cell_id", "value"])
				for tidx, time_value in enumerate(times_array.tolist()):
					for cell_id, cell_value in enumerate(values[tidx].tolist()):
						writer.writerow([int(tidx), float(time_value), int(cell_id), float(cell_value)])

	if getattr(options, "native_mesh_vtu", False):
		try:
			from hydromodpy.spatial.mesh.io import write_vtu

			for tidx, _time_value in enumerate(times_array.tolist()):
				cell_fields = {
					"cell_id": cell_ids.astype(float, copy=False),
					"top_elevation": np.asarray(model.solver_mesh.top, dtype=float).reshape(-1),
				}
				for name, values in cell_series.items():
					cell_fields[str(name)] = np.asarray(values[tidx], dtype=float).reshape(-1)
				mesh_with_data = model.solver_mesh.planar_mesh.with_cell_data(**cell_fields)
				write_vtu(
					os.path.join(mesh_dir, f"{prefix}_t({int(tidx)}).vtu"),
					mesh_with_data,
				)
		except ImportError as exc:
			logger.warning("Skipping native mesh VTU export: %s", exc)

	if getattr(options, "native_mesh_png", False):
		import matplotlib

		matplotlib.use("Agg", force=True)
		import matplotlib.pyplot as plt
		from matplotlib.ticker import ScalarFormatter
		from mpl_toolkits.axes_grid1 import make_axes_locatable

		from hydromodpy.spatial.mesh.plotting import plot_cell_values

		figure_dir = os.path.join(model.save_file, "_figures", "native_mesh")
		filesystem.create_folder(figure_dir)
		field_styles = {
			"watertable_elevation": ("Hydraulic head", "Head [m]", "viridis"),
			"watertable_depth": ("Water-table depth", "Top - h [m]", "Blues"),
			"seepage_areas": ("Seepage areas", "Seepage [m/day]", "Reds"),
			"outflow_drain": ("Drain discharge", "Discharge [m/day]", "magma"),
			"accumulation_flux": ("Accumulation flux", "Accumulated flow [m/day]", "plasma"),
			"concentration_seepage": ("Seepage concentration", "Concentration [-]", "viridis"),
			"mass_seepage": ("Seepage mass", "Mass [-]", "cividis"),
			"mass_accumulated": ("Accumulated mass", "Accumulated mass [-]", "inferno"),
		}

		for name, values in cell_series.items():
			for tidx, time_value in enumerate(times_array.tolist()):
				flat = np.asarray(values[tidx], dtype=float).reshape(-1).copy()
				flat[~np.isfinite(flat)] = np.nan
				flat[flat <= float(NODATA)] = np.nan
				finite = flat[np.isfinite(flat)]
				if finite.size == 0:
					continue

				vmin = float(np.nanmin(finite))
				vmax = float(np.nanmax(finite))
				if np.isclose(vmin, vmax):
					vmax = vmin + 1.0

				field_title, colorbar_label, cmap = field_styles.get(
					str(name),
					(str(name).replace("_", " ").title(), str(name).replace("_", " "), "viridis"),
				)
				fig, ax = plt.subplots(figsize=(7.2, 6.0), dpi=220)
				mappable = plot_cell_values(
					ax,
					model.solver_mesh.planar_mesh,
					flat,
					cmap=cmap,
					show_mesh=True,
					vmin=vmin,
					vmax=vmax,
				)
				ax.set_title(
					f"{field_title} | t={float(time_value):.12g} s",
					fontsize=10.5,
					loc="left",
					pad=5.0,
				)
				ax.set_xlabel("x (m)", fontsize=9)
				ax.set_ylabel("y (m)", fontsize=9)
				ax.ticklabel_format(style="plain", axis="both", useOffset=False)
				ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

				divider = make_axes_locatable(ax)
				cax = divider.append_axes("right", size="3.8%", pad=0.06)
				cbar = fig.colorbar(mappable, cax=cax)
				cbar.set_label(colorbar_label, fontsize=8.5, labelpad=6.0)
				cbar.ax.tick_params(labelsize=7.5, length=2.5, pad=1.5)
				formatter = ScalarFormatter(useMathText=True)
				formatter.set_powerlimits((-2, 3))
				cbar.formatter = formatter
				cbar.update_ticks()

				fig.subplots_adjust(left=0.08, right=0.94, bottom=0.11, top=0.9)
				fig.savefig(
					os.path.join(figure_dir, f"{prefix}_{name}_t({int(tidx)}).png"),
					bbox_inches="tight",
				)
				plt.close(fig)


def east_side_cell_ids(model: FlowPostprocessModel) -> set[int]:
	"""Return east-boundary cell ids for one DISV topological layer."""
	if getattr(model.solver_mesh, "is_structured", False):
		nrow = int(model.nrow)
		ncol = int(model.ncol)
		return {row * ncol + (ncol - 1) for row in range(nrow)}
	support = getattr(model, "runtime_mesh_support", None)
	if support is None:
		return set()
	return {int(cell_id) for cell_id in support.boundary_cell_indices_for_side("east_side").tolist()}


def compute_chd_outlet_discharge_east_side_m3_s(
	chd_records,
	*,
	ncpl: int,
	east_side_cell_ids: set[int],
) -> float:
	"""Return total positive east-side CHD outflow [m3/s] for one stress period."""
	if not chd_records or not east_side_cell_ids:
		return 0.0

	record = chd_records[0]
	if record is None or len(record) == 0:
		return 0.0

	if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
		node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
		q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
		iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
	else:
		iterator = ((int(item[0]), float(item[-1])) for item in record)

	discharge_m3_s = 0.0
	for node, q in iterator:
		if node <= 0:
			continue
		cell_id = (int(node) - 1) % int(ncpl)
		if cell_id not in east_side_cell_ids:
			continue
		discharge_m3_s += max(-float(q), 0.0)
	return float(discharge_m3_s)


def run_flow_post_processing(
	model: FlowPostprocessModel,
	options: ModflowPostprocessOptions | None = None,
) -> None:
	"""Run MODFLOW 6 flow post-processing and persist the selected outputs."""
	if options is None:
		options = ModflowPostprocessOptions()
	elif not isinstance(options, ModflowPostprocessOptions):
		raise TypeError("post_processing options must be ModflowPostprocessOptions")
	model.last_postprocess_options = options

	model.save_file = os.path.join(model.full_path, "_postprocess")
	filesystem.create_folder(model.save_file)
	model.tifs_file = os.path.join(model.save_file, "_rasters")
	filesystem.create_folder(model.tifs_file)

	head_path = os.path.join(model.full_path, f"{model.model_name}.hds")
	cbc_path = os.path.join(model.full_path, f"{model.model_name}.cbc")
	head_fpu = bf.HeadFile(head_path)
	cbb = open_budget_file(cbc_path)

	times = head_fpu.get_times()
	model.times = times
	dict_watertable_elevation = {}
	dict_watertable_depth = {}
	dict_seepage_areas = {}
	dict_outflow_drain = {}
	dict_outlet_discharge_east_side_m3_s = {}
	dict_accumulation_flux = {}
	can_export_raster = bool(
		getattr(model.solver_mesh, "is_structured", False)
		and getattr(model, "dem_watershed_path", "")
	)

	ncpl = int(model.ncpl)
	dem_mask_flat = np.asarray(model.dem_mask, dtype=bool).reshape(-1)
	dem_flat = np.asarray(model.dem, dtype=float).reshape(-1)
	east_cells = east_side_cell_ids(model)

	for item, time in enumerate(times):
		head = head_fpu.get_data(totim=time)
		wt = compute_watertable_elevation(head)

		if options.watertable_elevation:
			wt_out = wt.copy()
			wt_out[dem_mask_flat] = NODATA
			dict_watertable_elevation[item] = model._to_export_array(wt_out)
			if can_export_raster and (options.export_all_tif or item == 0):
				raster_io.export_tif(
					model.dem_watershed_path,
					model._to_export_array(wt_out),
					os.path.join(model.tifs_file, f"watertable_elevation_t({item}).tif"),
					NODATA,
				)

		if options.watertable_depth:
			wtd = compute_watertable_depth(
				watertable_elevation=wt,
				dem=dem_flat,
				dem_mask=dem_mask_flat,
			)
			dict_watertable_depth[item] = model._to_export_array(wtd)
			if can_export_raster and (options.export_all_tif or item == 0):
				raster_io.export_tif(
					model.dem_watershed_path,
					model._to_export_array(wtd),
					os.path.join(model.tifs_file, f"watertable_depth_t({item}).tif"),
					NODATA,
				)

		drn = get_budget_records_or_none(cbb, kstpkper=(0, item), text="DRN")
		outflow, seepage = compute_drain_outflow_and_seepage(drn, ncpl=ncpl)
		outflow[dem_mask_flat] = NODATA
		seepage[dem_mask_flat] = NODATA

		outflow_tif_path = os.path.join(model.tifs_file, f"outflow_drain_t({item}).tif")
		if options.outflow_drain:
			dict_outflow_drain[item] = model._to_export_array(outflow)
		if options.outflow_drain or options.accumulation_flux:
			if can_export_raster and (options.accumulation_flux or options.export_all_tif or item == 0):
				raster_io.export_tif(
					model.dem_watershed_path,
					model._to_export_array(outflow),
					outflow_tif_path,
					NODATA,
				)
		if options.seepage_areas:
			dict_seepage_areas[item] = model._to_export_array(seepage)
			if can_export_raster and (options.export_all_tif or item == 0):
				raster_io.export_tif(
					model.dem_watershed_path,
					model._to_export_array(seepage),
					os.path.join(model.tifs_file, f"seepage_areas_t({item}).tif"),
					NODATA,
				)

		if options.outlet_discharge_east_side_m3_s:
			chd = get_budget_records_or_none(cbb, kstpkper=(0, item), text="CHD")
			outlet_discharge_m3_s = compute_chd_outlet_discharge_east_side_m3_s(
				chd,
				ncpl=ncpl,
				east_side_cell_ids=east_cells,
			)
			dict_outlet_discharge_east_side_m3_s[item] = np.asarray(
				[outlet_discharge_m3_s],
				dtype=float,
			)

		if options.accumulation_flux and can_export_raster and model.solver_mesh.is_structured:
			routing_ctx = model._ensure_solver_routing_context()
			accumulated_flow = masstransfer.Masstransfer(
				model.geographic,
				f"outflow_drain_t({item}).tif",
				f"tracept_t({item}).shp",
				f"accumulation_flux_t({item}).tif",
				extraction_folder=model.save_file,
				routing_fill_path=routing_ctx.correc_path,
				routing_direc_path=routing_ctx.direc_path,
			)
			accumulated_flow.trace_cumulated()
			with rasterio.open(os.path.join(model.tifs_file, f"accumulation_flux_t({item}).tif")) as src:
				dict_accumulation_flux[item] = src.read(1)
		elif options.accumulation_flux and not getattr(model.solver_mesh, "is_structured", False):
			accumulated_flow = accumulate_unstructured_cell_values(
				model,
				local_values=np.where(outflow <= float(NODATA), 0.0, outflow),
				reference_values=np.where(dem_mask_flat, np.nan, dem_flat),
				inactive_mask=dem_mask_flat,
			)
			accumulated_flow[dem_mask_flat] = float(NODATA)
			dict_accumulation_flux[item] = model._to_export_array(accumulated_flow)

	if options.watertable_elevation:
		np.save(os.path.join(model.save_file, "watertable_elevation"), dict_watertable_elevation)
	if options.watertable_depth:
		np.save(os.path.join(model.save_file, "watertable_depth"), dict_watertable_depth)
	if options.seepage_areas:
		np.save(os.path.join(model.save_file, "seepage_areas"), dict_seepage_areas)
	if options.outflow_drain:
		np.save(os.path.join(model.save_file, "outflow_drain"), dict_outflow_drain)
	if options.outlet_discharge_east_side_m3_s:
		np.save(
			os.path.join(model.save_file, "outlet_discharge_east_side_m3_s"),
			dict_outlet_discharge_east_side_m3_s,
		)
	if options.accumulation_flux:
		np.save(os.path.join(model.save_file, "accumulation_flux"), dict_accumulation_flux)
	export_native_mesh_outputs(
		model,
		options=options,
		times=times,
		datasets={
			"watertable_elevation": dict_watertable_elevation,
			"watertable_depth": dict_watertable_depth,
			"seepage_areas": dict_seepage_areas,
			"outflow_drain": dict_outflow_drain,
			"accumulation_flux": dict_accumulation_flux,
		},
		prefix="flow",
	)
	export_runtime_support_overview(model, options=options)


def run_transport_post_processing(
	transport_model: TransportPostprocessModel,
	model_mt3dms: object,
	*,
	concentration_seepage: bool = True,
	mass_seepage: bool = True,
	mass_accumulated: bool = False,
	export_all_tif: bool = False,
	options: ModflowPostprocessOptions | None = None,
) -> None:
	"""Run MODFLOW 6 transport post-processing on the paired GWT outputs."""
	del model_mt3dms
	runtime_options = transport_model._resolve_postprocess_options(
		export_all_tif=export_all_tif,
		options=options,
	)
	export_all_tif = bool(runtime_options.export_all_tif)
	transport_model.save_file = os.path.join(transport_model.full_path, "_postprocess")
	filesystem.create_folder(transport_model.save_file)
	transport_model.tifs_file = os.path.join(transport_model.save_file, "_rasters")
	filesystem.create_folder(transport_model.tifs_file)

	path_ucn = os.path.join(transport_model.full_path, f"{transport_model.model_name_mt}.ucn")
	conc_reader = None
	try:
		ucnobj = bf.UcnFile(path_ucn)
		conc_reader = ucnobj
		concobj_1c = ucnobj.get_alldata(mflay=None)
	except Exception:
		try:
			headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="double")
			conc_reader = headobj
			concobj_1c = headobj.get_alldata(mflay=None)
		except Exception:
			headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="single")
			conc_reader = headobj
			concobj_1c = headobj.get_alldata(mflay=None)
	concobj_1c[concobj_1c >= 1e30] = np.nan
	conc_last_idx = max(int(concobj_1c.shape[0]) - 1, 0)
	times = list(getattr(transport_model.model_modflow, "times", []) or [])
	if len(times) != int(transport_model.model_modflow.nper):
		try:
			times = [float(value) for value in conc_reader.get_times()]
		except Exception:
			times = []
	if len(times) != int(transport_model.model_modflow.nper):
		times = [float(i + 1) for i in range(int(transport_model.model_modflow.nper))]

	outflow_drain = np.load(
		os.path.join(transport_model.save_file, "outflow_drain.npy"),
		allow_pickle=True,
	).item()
	dem_mask = np.asarray(
		getattr(transport_model.model_modflow, "dem_mask", transport_model.model_modflow.dem < float(NODATA)),
		dtype=bool,
	).reshape(-1)

	dict_concentration_seepage = {}
	dict_mass_seepage = {}
	dict_mass_accumulated = {}
	can_export_raster = bool(
		getattr(transport_model.model_modflow.solver_mesh, "is_structured", False)
		and getattr(transport_model.model_modflow, "dem_watershed_path", "")
	)

	def _reshape_for_export(arr):
		return transport_model.model_modflow._to_export_array(np.asarray(arr, dtype=float).reshape(-1))

	for i in range(transport_model.model_modflow.nper):
		the_time = str(i + 1)
		seep = outflow_drain.get(i, np.zeros(int(transport_model.model_modflow.ncpl), dtype=float))
		seep = np.asarray(seep, dtype=float).reshape(-1)
		conc_time_idx = min(i, conc_last_idx)
		mass_surf = None

		if concentration_seepage:
			conc_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
			conc_surf[seep <= 0] = float(NODATA)
			conc_surf[dem_mask] = float(NODATA)
			dict_concentration_seepage[i] = _reshape_for_export(conc_surf)
			if can_export_raster and (export_all_tif or i == 0):
				raster_io.export_tif(
					transport_model.model_modflow.dem_watershed_path,
					_reshape_for_export(conc_surf),
					os.path.join(transport_model.tifs_file, f"concentration_seepage_t({the_time}).tif"),
					NODATA,
				)

		if mass_seepage or mass_accumulated:
			mass_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
			mass_surf[seep <= 0] = np.nan
			mass_surf = mass_surf * seep
			mass_surf[dem_mask] = float(NODATA)
			mass_surf = np.where(np.isnan(mass_surf), float(NODATA), mass_surf)
		if mass_seepage and mass_surf is not None:
			dict_mass_seepage[i] = _reshape_for_export(mass_surf)
			if can_export_raster and (export_all_tif or i == 0):
				raster_io.export_tif(
					transport_model.model_modflow.dem_watershed_path,
					_reshape_for_export(mass_surf),
					os.path.join(transport_model.tifs_file, f"mass_seepage_t({the_time}).tif"),
					NODATA,
				)

		if mass_accumulated and can_export_raster:
			routing_ctx = transport_model.model_modflow._ensure_solver_routing_context()
			accumulated_mass = masstransfer.Masstransfer(
				transport_model.model_modflow.geographic,
				f"mass_seepage_t({the_time}).tif",
				f"tracept_conc_t({the_time}).shp",
				f"mass_accumulated_t({the_time}).tif",
				extraction_folder=transport_model.save_file,
				routing_fill_path=routing_ctx.correc_path,
				routing_direc_path=routing_ctx.direc_path,
			)
			accumulated_mass.trace_cumulated()
			with rasterio.open(os.path.join(transport_model.tifs_file, f"mass_accumulated_t({the_time}).tif")) as src:
				dict_mass_accumulated[i] = src.read(1)
		elif (
			mass_accumulated
			and mass_surf is not None
			and not getattr(transport_model.model_modflow.solver_mesh, "is_structured", False)
		):
			accumulated_mass = accumulate_unstructured_cell_values(
				transport_model.model_modflow,
				local_values=np.where(mass_surf <= float(NODATA), 0.0, mass_surf),
				reference_values=np.where(
					dem_mask,
					np.nan,
					np.asarray(transport_model.model_modflow.dem, dtype=float).reshape(-1),
				),
				inactive_mask=dem_mask,
			)
			accumulated_mass[dem_mask] = float(NODATA)
			dict_mass_accumulated[i] = _reshape_for_export(accumulated_mass)

	if concentration_seepage:
		np.save(os.path.join(transport_model.save_file, "concentration_seepage"), dict_concentration_seepage)
	if mass_seepage:
		np.save(os.path.join(transport_model.save_file, "mass_seepage"), dict_mass_seepage)
	if mass_accumulated:
		np.save(os.path.join(transport_model.save_file, "mass_accumulated"), dict_mass_accumulated)
	transport_model.model_modflow.save_file = transport_model.save_file
	export_native_mesh_outputs(
		transport_model.model_modflow,
		options=runtime_options,
		times=times,
		datasets={
			"concentration_seepage": dict_concentration_seepage,
			"mass_seepage": dict_mass_seepage,
			"mass_accumulated": dict_mass_accumulated,
		},
		prefix="transport",
	)


__all__ = [
	"BudgetReaderLike",
	"FlowPostprocessModel",
	"RoutingContextLike",
	"SolverMeshLike",
	"TransportPostprocessModel",
	"NODATA",
	"accumulate_unstructured_cell_values",
	"build_unstructured_cell_adjacency",
	"compute_chd_outlet_discharge_east_side_m3_s",
	"compute_drain_outflow_and_seepage",
	"compute_watertable_depth",
	"compute_watertable_elevation",
	"east_side_cell_ids",
	"export_native_mesh_outputs",
	"get_budget_records_or_none",
	"native_cell_series_payload",
	"native_mesh_exports_enabled",
	"open_budget_file",
	"run_flow_post_processing",
	"run_transport_post_processing",
]
