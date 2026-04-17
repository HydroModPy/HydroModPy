"""MODFLOW 6 flow and transport solvers aligned with HydroModPy workflow APIs."""

from __future__ import annotations

import os
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from numbers import Real

import flopy
import numpy as np

from hydromodpy.process.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow_common import (
	SolverGridContext,
	SolverRoutingContext,
	build_solver_routing_context,
	ensure_platform_executable,
	write_grid_array_to_raster,
)
from hydromodpy.solver.modflow_common.discretization_spatial import (
	build_spatial_discretization,
)
from hydromodpy.solver.modflow_common.discretization_temporal import (
	build_temporal_discretization_from_time_grid,
)
from hydromodpy.solver.modflow_common.options import (
	ModflowPostprocessOptions,
	ModflowPreprocessOptions,
	ModflowRunOptions,
)
from hydromodpy.solver.contracts import Solver
from hydromodpy.solver.modflow6.modflow6_config import (
	Modflow6Config,
	_coerce_modflow6_config,
)
from hydromodpy.solver.modflow6.property_mapping import (
	resolve_required_flow_properties,
	resolve_flow_property_arrays,
)
from hydromodpy.solver.modflow6 import flow_to_modflow_adapter as mf6_flow_adapter
from hydromodpy.solver.modflow6 import postprocess as mf6_postprocess
from hydromodpy.solver.modflow_common.runtime_arrays import (
	build_concentration_runtime_overrides,
)
from hydromodpy.core.units import (
	convert_payload_to_m,
	convert_payload_to_m_per_s,
	factor_to_m2_per_s,
	normalize_length_unit,
)
from hydromodpy.core.units.volumetric_flow import (
	convert_to_m3_per_s,
	normalize_m3_per_s_unit,
)
from hydromodpy.core.tools import get_logger, toolbox

logger = get_logger(__name__)


def _mf6_safe_name(name: str, max_len: int = 16) -> str:
	text = str(name)
	if len(text) <= max_len:
		return text
	if max_len <= 6:
		return text[:max_len]
	digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
	prefix_len = max_len - 7
	return f"{text[:prefix_len]}_{digest}"


@dataclass(frozen=True)
class Modflow6RuntimeParams:
	"""Minimal runtime parameters for MODFLOW 6 simulation."""

	engine: str = "mf6"
	executable_name: str = "mf6"
	print_flows: bool = False
	print_input: bool = False
	save_flows: bool = True
	ims_complexity: str = "COMPLEX"


class Modflow6(Solver):
	"""Flow solver based on MODFLOW 6 (GWF)."""

	def __init__(
		self,
		geographic: object,
		modflow_config: Modflow6Config | Mapping[str, object] | None = None,
		model_folder: str = "HydroModPy_outputs",
		model_name: str = "Default",
		bin_path: str = "bin",
		preprocess_options: ModflowPreprocessOptions | None = None,
	):
		self.model_folder = model_folder
		if not os.path.exists(self.model_folder):
			toolbox.create_folder(self.model_folder)

		self.model_name = model_name
		self.model_name_mf6 = _mf6_safe_name(model_name)
		self.geographic = geographic
		self.flow = None
		self.domain = None
		self.flow_regime: str | None = None
		self.prob_cells = 0

		self.full_path = os.path.join(model_folder, model_name)
		self.dem_watershed_path = None
		self.grid_ctx: SolverGridContext | None = None
		self.routing_ctx: SolverRoutingContext | None = None

		self.modflow_config = _coerce_modflow6_config(modflow_config)
		runtime = self.modflow_config.runtime
		exe_name = getattr(runtime, "mf6_executable_name", None) or getattr(runtime, "executable_name", None)
		if not exe_name:
			if os.name == "nt":
				exe_name = "mf6.exe"
			else:
				exe_name = "mf6"
		if os.path.isabs(exe_name):
			self.exe = exe_name
		else:
			platform_dir = "win" if os.name == "nt" else ("mac" if os.uname().sysname.lower() == "darwin" else "linux")
			self.exe = os.path.join(bin_path, platform_dir, exe_name)
		self.exe = str(ensure_platform_executable(self.exe))

		self.resolution = geographic.dem_res
		self.xul = geographic.xmin
		self.yul = geographic.ymax
		self.sink = getattr(geographic, "depressions_data", None)

		self.preprocess_options = preprocess_options or ModflowPreprocessOptions()
		self._apply_preprocess_options(self.preprocess_options)
		self._evt_rate_payload: dict[int, object] | None = None
		self._pending_negative_to_evt = False
		self._heterogeneous_recharge_source = None
		self._heterogeneous_negative_to_evt = False
		self._heterogeneous_interpolation_method = "nearest"

	def _select_active_dem(self, box: bool) -> None:
		if box:
			self.dem_watershed_path = self.geographic.watershed_box_buff_dem
		else:
			self.dem_watershed_path = self.geographic.watershed_buff_dem

	def _apply_preprocess_options(self, options: ModflowPreprocessOptions | None = None) -> None:
		if options is None:
			options = self.preprocess_options
		if not isinstance(options, ModflowPreprocessOptions):
			raise TypeError("pre_processing options must be a ModflowPreprocessOptions instance.")

		self.preprocess_options = options
		self.sink_fill = bool(options.sink_fill)
		self.recharge = getattr(options, "recharge", None)
		self.first_clim = getattr(options, "first_clim", None)
		self.time_grid = getattr(options, "time_grid", None)
		self.check_grid = bool(options.check_grid)
		self._select_active_dem(box=bool(options.box))

	def _to_export_array(self, flat_array: np.ndarray) -> np.ndarray:
		"""Reshape flat (ncpl,) to (nrow, ncol) for raster export (structured only)."""
		return self.solver_mesh.reshape_to_grid(flat_array)

	def _write_solver_grid_template(self) -> str:
		if self.grid_ctx is None:
			raise ValueError("grid_ctx must exist before writing a solver grid template")
		if not self.solver_mesh.is_structured:
			# No raster template for unstructured grids.
			return ""
		os.makedirs(self.full_path, exist_ok=True)
		template_path = os.path.join(self.full_path, "_solver_grid_template.tif")
		top_2d = self.solver_mesh.reshape_to_grid(self.solver_mesh.top)
		write_grid_array_to_raster(
			grid=self.grid_ctx.grid,
			data=top_2d,
			output_path=template_path,
			nodata=float(self.grid_ctx.grid.nodata),
		)
		self.grid_ctx.template_raster_path = template_path
		return template_path

	def _ensure_solver_routing_context(self) -> SolverRoutingContext:
		"""Build hydrologic routing rasters aligned with the solver grid."""
		if self.routing_ctx is not None:
			return self.routing_ctx
		if self.grid_ctx is None:
			raise ValueError("grid_ctx must exist before building solver routing products")

		self.routing_ctx = build_solver_routing_context(
			dem_path=self.dem_watershed_path,
			output_dir=os.path.join(self.full_path, "_solver_routing"),
			dem_correc_type=str(getattr(self.geographic, "dem_correc_type", "breach")),
			crs_project=getattr(self.geographic, "crs_proj", None),
		)
		return self.routing_ctx

	def _resolve_flow_regime(self) -> str | None:
		if self.flow is None:
			return None

		flow_regime = None
		flow_cfg = getattr(self.flow, "config", None)
		if flow_cfg is not None:
			flow_regime = getattr(flow_cfg, "flow_regime", None)
		if flow_regime is None:
			flow_regime = getattr(self.flow, "flow_regime", None)
		if flow_regime is None:
			return None

		flow_regime_text = str(flow_regime).strip().lower()
		if flow_regime_text not in {"steady", "transient"}:
			raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
		return flow_regime_text

	def _validate_pre_processing_inputs(self) -> None:
		if self.flow is None:
			raise ValueError("pre_processing requires a configured Flow object.")
		if self.domain is None:
			raise ValueError("pre_processing requires a configured Domain object.")
		flow_regime = self._resolve_flow_regime()
		if flow_regime is None:
			raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
		self.flow_regime = flow_regime
		if self.time_grid is None and self.flow_regime != "steady":
			raise ValueError(
				"Launcher flow preprocessing requires preprocess_options.time_grid "
				"derived from [simulation.time] for transient flow runs. Solver tgrid fallback is no longer supported."
			)

	def _well_cell_to_disv(self, lay: int, row: int, col: int) -> tuple[int, int]:
		"""Convert (lay, row, col) well address to DISV (lay, cell_id)."""
		return (lay, row * int(self.ncol) + col)

	def _require_runtime_mesh_support(self, *, label: str) -> object:
		"""Return runtime gmsh support metadata or raise a clear error."""
		support = getattr(self, "runtime_mesh_support", None)
		if support is None:
			raise ValueError(
				f"{label} requires runtime gmsh support metadata but mesh_support is unavailable."
			)
		return support

	def _resolve_well_disv_cell(self, *, well_id: str, well_cfg: object, grid: object | None) -> tuple[int, int]:
		"""Resolve one well payload to one DISV (layer, cell_id) tuple."""
		def _value(name: str, default=None):
			if isinstance(well_cfg, Mapping):
				return well_cfg.get(name, default)
			return getattr(well_cfg, name, default)

		cell_payload = _value("cell")
		location_mode = str(_value("location_mode", "") or "").strip().lower()
		solver_mesh = getattr(self, "solver_mesh", None)

		if cell_payload is not None:
			cell_seq = list(cell_payload)
			if len(cell_seq) != 3:
				raise ValueError(
					f"flow.sinks_sources.wells.{well_id}.cell must contain [lay, row, col]."
				)
			return self._well_cell_to_disv(
				int(cell_seq[0]),
				int(cell_seq[1]),
				int(cell_seq[2]),
			)

		if location_mode in {"", "cell"}:
			raise ValueError(
				f"flow.sinks_sources.wells.{well_id} requires either cell=[lay,row,col] "
				"or coordinate-based location fields."
			)

		if solver_mesh is None or getattr(solver_mesh, "is_structured", False):
			if grid is None:
				raise ValueError(
					f"flow.sinks_sources.wells.{well_id} cannot resolve coordinate-based addressing "
					"without one structured solver grid."
				)
			if hasattr(well_cfg, "resolve_cell"):
				lay, row, col = well_cfg.resolve_cell(grid)
			else:
				layer = int(_value("layer", 0) or 0)
				if location_mode == "absolute_xy":
					x_m = float(_value("x"))
					y_m = float(_value("y"))
				elif location_mode == "relative_xy":
					x_m = float(grid.xmin) + float(_value("x_rel")) * (float(grid.xmax) - float(grid.xmin))
					y_m = float(grid.ymin) + float(_value("y_rel")) * (float(grid.ymax) - float(grid.ymin))
				else:
					raise ValueError(
						f"Unsupported well location mode for flow.sinks_sources.wells.{well_id}: {location_mode!r}."
					)
				col = int((x_m - float(grid.xmin)) / float(grid.dx))
				row = int((float(grid.ymax) - y_m) / float(grid.dy))
				col = min(max(col, 0), int(grid.ncol) - 1)
				row = min(max(row, 0), int(grid.nrow) - 1)
				lay = layer
			return self._well_cell_to_disv(int(lay), int(row), int(col))

		support = self._require_runtime_mesh_support(
			label=f"flow.sinks_sources.wells.{well_id}",
		)
		layer = int(_value("layer", 0) or 0)
		if location_mode == "absolute_xy":
			x_m = float(_value("x"))
			y_m = float(_value("y"))
		elif location_mode == "relative_xy":
			x_rel = float(_value("x_rel"))
			y_rel = float(_value("y_rel"))
			x_m = float(support.x_min_m) + x_rel * (float(support.x_max_m) - float(support.x_min_m))
			y_m = float(support.y_min_m) + y_rel * (float(support.y_max_m) - float(support.y_min_m))
		else:
			raise ValueError(
				f"Unsupported well location mode for flow.sinks_sources.wells.{well_id}: {location_mode!r}."
			)
		cell_id = int(support.locate_cell_index_for_point(x_m, y_m, allow_nearest=True))
		return (layer, cell_id)

	def _build_well_stress_period_data(self, n_stress_periods: int) -> dict[int, list[list[float]]]:
		return mf6_flow_adapter.build_well_stress_period_data(self, n_stress_periods)

	@staticmethod
	def _is_scalar_number(value: object) -> bool:
		return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)

	def _boundary_conditions_mapping(self) -> Mapping[str, object]:
		boundary_conditions = getattr(self.flow, "boundary_conditions", {})
		if not isinstance(boundary_conditions, Mapping):
			raise TypeError("flow.boundary_conditions must be a mapping")
		return boundary_conditions

	@staticmethod
	def _boundary_attr(boundary: object, name: str, default=None):
		"""Read one boundary attribute from either a mapping or a typed payload."""
		if isinstance(boundary, Mapping):
			return boundary.get(name, default)
		return getattr(boundary, name, default)

	def _is_bc_active(self, bc_id: str) -> bool:
		active = getattr(self.flow, "active_bc", [])
		return bc_id in active

	def _boundary_period_series(self, *, value: object, label: str) -> np.ndarray:
		if self._is_scalar_number(value):
			return np.full((int(self.nper),), float(value), dtype=float)
		if not isinstance(value, (np.ndarray, list, tuple)):
			raise TypeError(f"{label} must be numeric or a sequence of numeric values")
		series = np.asarray(value, dtype=float).reshape(-1)
		if series.size == 0:
			raise ValueError(f"{label} cannot be empty when using time series")
		if series.size == 1:
			return np.full((int(self.nper),), float(series[0]), dtype=float)
		if series.size != int(self.nper):
			raise ValueError(
				f"{label} length ({series.size}) must be 1 or match nper ({int(self.nper)})"
			)
		return series.astype(float)

	def _coerce_length_series_to_m(self, *, values: object, units: object, label: str) -> np.ndarray:
		source_units = normalize_length_unit(str(units).strip() or "m")
		return np.asarray(
			convert_payload_to_m(values, unit=source_units, label=label),
			dtype=float,
		)

	@staticmethod
	def _forcing_units(forcing: object, *, fallback: object) -> object:
		if isinstance(forcing, Mapping):
			return forcing.get("units", fallback)
		return getattr(forcing, "units", fallback)

	def _coerce_conductance_series_to_m2_per_s(
		self,
		*,
		values: object,
		units: object,
		label: str,
	) -> np.ndarray:
		factor = factor_to_m2_per_s(str(units).strip() or "m2/s")
		return np.asarray(values, dtype=float) * float(factor)

	def _boundary_start_value(self, *, value: object, label: str) -> float:
		return float(self._boundary_period_series(value=value, label=label)[0])

	def _resolve_side_boundary_series(self, *, boundary: object, bc_id: str) -> np.ndarray:
		forcing = self._boundary_attr(boundary, "forcing", None)
		if forcing is not None:
			raw_values = resolve_period_values_from_forcing(
					forcing=forcing,
					simulation_window=None if self.time_grid is None else self.time_grid.window,
					nper=int(self.nper),
					label=f"flow.bc.{bc_id}.forcing",
				)
			return self._coerce_length_series_to_m(
				values=raw_values,
				units=self._forcing_units(
					forcing,
					fallback=self._boundary_attr(boundary, "units", "m"),
				),
				label=f"flow.bc.{bc_id}.forcing",
			)
		return self._coerce_length_series_to_m(
			values=self._boundary_period_series(
			value=self._boundary_attr(boundary, "value", None),
			label=f"flow.bc.{bc_id}.value",
			),
			units=self._boundary_attr(boundary, "units", "m"),
			label=f"flow.bc.{bc_id}.value",
		)

	def _boundary_support_cell_ids(self, *, boundary: object, bc_id: str) -> list[int]:
		"""Return flat cell ids selected by one BC support definition."""
		solver_mesh = getattr(self, "solver_mesh", None)
		support_label = self._boundary_attr(boundary, "support_label", None)
		if support_label is not None and not (solver_mesh is None or getattr(solver_mesh, "is_structured", False)):
			support = self._require_runtime_mesh_support(label=f"flow.bc.{bc_id}")
			cell_ids = support.cell_indices_for_label(str(support_label))
			if cell_ids.size == 0:
				raise ValueError(
					f"flow.bc.{bc_id}.support_label='{support_label}' did not match any runtime mesh support."
				)
			return [int(cell_id) for cell_id in cell_ids.tolist()]
		return self._side_boundary_cell_ids(bc_id)

	def _side_boundary_cell_ids(self, bc_id: str) -> list[int]:
		"""Return flat cell IDs touched by one side boundary."""
		solver_mesh = getattr(self, "solver_mesh", None)
		if solver_mesh is None or getattr(solver_mesh, "is_structured", False):
			nrow, ncol = int(self.nrow), int(self.ncol)
			if bc_id == "west_side":
				return [i * ncol for i in range(nrow)]
			if bc_id == "east_side":
				return [i * ncol + (ncol - 1) for i in range(nrow)]
			if bc_id == "north_side":
				return list(range(ncol))
			if bc_id == "south_side":
				return list(range((nrow - 1) * ncol, nrow * ncol))
			raise ValueError(f"Unsupported side boundary id: {bc_id}")

		support = self._require_runtime_mesh_support(label=f"flow.bc.{bc_id}")
		return [
			int(cell_id)
			for cell_id in support.boundary_cell_indices_for_side(bc_id).tolist()
		]

	def _iter_side_boundary_cells(self, bc_id: str):
		"""Yield (lay, cell_id) tuples for DISV boundary cells."""
		cell_ids = self._side_boundary_cell_ids(bc_id)
		for ilay in range(int(self.nlay)):
			for cid in cell_ids:
				yield ilay, cid

	def _apply_side_boundary_start_heads(self, strt: np.ndarray) -> np.ndarray:
		"""Apply side boundary start heads on flat (nlay, ncpl) strt array."""
		bc = self._boundary_conditions_mapping()
		for bc_id in ("west_side", "east_side", "north_side", "south_side"):
			if not self._is_bc_active(bc_id):
				continue
			boundary = bc.get(bc_id)
			if boundary is None:
				continue
			start_value = float(self._resolve_side_boundary_series(boundary=boundary, bc_id=bc_id)[0])
			cell_ids = self._boundary_support_cell_ids(boundary=boundary, bc_id=bc_id)
			for ilay in range(strt.shape[0]):
				strt[ilay, cell_ids] = start_value
		return strt

	def _resolve_head_initial_condition(self):
		"""Return the head initial-condition payload from the flow configuration."""
		initial_conditions = getattr(self.flow, "initial_conditions", None)
		if initial_conditions is None:
			return None
		if isinstance(initial_conditions, Mapping):
			return initial_conditions.get("h")
		return getattr(initial_conditions, "h", None)

	@staticmethod
	def _initial_condition_field(initial_condition, field_name: str, default=None):
		"""Read one field from either a mapping payload or a typed IC object."""
		if isinstance(initial_condition, Mapping):
			return initial_condition.get(field_name, default)
		return getattr(initial_condition, field_name, default)

	def _rewet_is_enabled(self) -> bool:
		"""Return whether MF6 rewetting is enabled for the current run."""
		runtime = getattr(self.modflow_config, "runtime", None)
		enable_rewet = getattr(runtime, "mf6_enable_rewet", None)
		return bool(enable_rewet) if enable_rewet is not None else False

	def _build_start_heads(self, solver_mesh) -> np.ndarray:
		"""Build MF6 starting heads as flat (nlay, ncpl) for DISV."""
		h_ic = self._resolve_head_initial_condition()
		if h_ic is None:
			raise ValueError("flow.initial_conditions.h is required for Modflow6 pre_processing")

		ncpl = solver_mesh.n_cells
		top_flat = solver_mesh.top  # (ncpl,)
		botm_flat = solver_mesh.botm  # (nlay, ncpl)
		initial_type = str(self._initial_condition_field(h_ic, "type", "")).strip().lower()
		if initial_type == "top":
			strt = np.tile(top_flat, (self.nlay, 1))
		elif initial_type in {"bot", "bottom"}:
			strt = np.tile(botm_flat[-1], (self.nlay, 1))
		elif initial_type == "custom":
			strt = np.full(
				(self.nlay, ncpl),
				float(self._initial_condition_field(h_ic, "value")),
				dtype=float,
			)
		else:
			raise ValueError("flow.initial_conditions.h.type must be one of: top, bottom, custom")
		ocean_series = self._resolve_ocean_boundary_series()
		ocean_support_mask = self._ocean_chd_support_mask(ocean_series)
		if np.any(ocean_support_mask):
			for ilay in range(int(self.nlay)):
				strt[ilay][ocean_support_mask] = float(ocean_series[0])
		stream_series = self._resolve_stream_boundary_series()
		stream_support_mask = self._stream_chd_support_mask(stream_series)
		if np.any(stream_support_mask):
			for ilay in range(int(self.nlay)):
				strt[ilay][stream_support_mask] = float(stream_series[0])
		return self._apply_side_boundary_start_heads(strt)

	def _resolve_ocean_boundary_series(self) -> np.ndarray | None:
		if not self._is_bc_active("ocean"):
			return None
		boundary = self._boundary_conditions_mapping().get("ocean")
		if boundary is None:
			return None
		forcing = self._boundary_attr(boundary, "forcing", None)
		if forcing is not None:
			raw_values = resolve_period_values_from_forcing(
					forcing=forcing,
					simulation_window=None if self.time_grid is None else self.time_grid.window,
					nper=int(self.nper),
					label="flow.bc.ocean.forcing",
				)
			return self._coerce_length_series_to_m(
				values=raw_values,
				units=self._forcing_units(
					forcing,
					fallback=self._boundary_attr(boundary, "units", "m"),
				),
				label="flow.bc.ocean.forcing",
			)
		return self._coerce_length_series_to_m(
			values=self._boundary_period_series(
			value=self._boundary_attr(boundary, "value", None),
			label="flow.bc.ocean.value",
			),
			units=self._boundary_attr(boundary, "units", "m"),
			label="flow.bc.ocean.value",
		)

	def _resolve_stream_boundary_series(self) -> np.ndarray | None:
		if not self._is_bc_active("stream"):
			return None
		boundary = self._boundary_conditions_mapping().get("stream")
		if boundary is None:
			return None
		forcing = self._boundary_attr(boundary, "forcing", None)
		if forcing is not None:
			raw_values = resolve_period_values_from_forcing(
					forcing=forcing,
					simulation_window=None if self.time_grid is None else self.time_grid.window,
					nper=int(self.nper),
					label="flow.bc.stream.forcing",
				)
			return self._coerce_length_series_to_m(
				values=raw_values,
				units=self._forcing_units(
					forcing,
					fallback=self._boundary_attr(boundary, "units", "m"),
				),
				label="flow.bc.stream.forcing",
			)
		return self._coerce_length_series_to_m(
			values=self._boundary_period_series(
			value=self._boundary_attr(boundary, "value", None),
			label="flow.bc.stream.value",
			),
			units=self._boundary_attr(boundary, "units", "m"),
			label="flow.bc.stream.value",
		)

	def _ocean_chd_support_mask(self, ocean_series: np.ndarray | None) -> np.ndarray:
		"""Return flat (ncpl,) boolean mask for ocean CHD cells."""
		if ocean_series is None or np.asarray(ocean_series, dtype=float).size == 0:
			return np.zeros(int(self.ncpl), dtype=bool)
		sea_threshold = float(np.max(np.asarray(ocean_series, dtype=float)))
		dem_flat = np.asarray(self.dem, dtype=float).reshape(-1)
		mask_flat = np.asarray(self.dem_mask, dtype=bool).reshape(-1)
		return (~mask_flat) & (dem_flat <= sea_threshold)

	def _build_ocean_boundary_chd_spd(self) -> tuple[dict[int, list[list[float]]], np.ndarray]:
		ocean_series = self._resolve_ocean_boundary_series()
		ocean_support_mask = self._ocean_chd_support_mask(ocean_series)
		spd = {kper: [] for kper in range(int(self.nper))}
		if ocean_series is None or not np.any(ocean_support_mask):
			return spd, ocean_support_mask

		cell_ids = np.where(ocean_support_mask)[0]
		for kper, head in enumerate(np.asarray(ocean_series, dtype=float)):
			period_cells: list[list[float]] = []
			for ilay in range(int(self.nlay)):
				for cid in cell_ids.tolist():
					period_cells.append([ilay, cid, float(head)])
			spd[kper] = period_cells
		return spd, ocean_support_mask

	def _stream_chd_support_mask(self, stream_series: np.ndarray | None) -> np.ndarray:
		"""Return flat (ncpl,) boolean mask for stream CHD cells."""
		if stream_series is None or np.asarray(stream_series, dtype=float).size == 0:
			return np.zeros(int(self.ncpl), dtype=bool)
		boundary = self._boundary_conditions_mapping().get("stream")
		support = self._require_runtime_mesh_support(label="flow.bc.stream")
		support_label = None if boundary is None else self._boundary_attr(boundary, "support_label", None)
		if support_label is None:
			cell_ids = np.asarray(support.river_cell_indices(), dtype=int).reshape(-1)
		else:
			cell_ids = np.asarray(support.cell_indices_for_label(str(support_label)), dtype=int).reshape(-1)
		if cell_ids.size == 0:
			raise ValueError(
				"Boundary 'stream' is active but its selected runtime mesh support is empty."
			)
		mask = np.zeros(int(self.ncpl), dtype=bool)
		mask[cell_ids] = True
		return mask

	def _build_stream_boundary_chd_spd(self) -> tuple[dict[int, list[list[float]]], np.ndarray]:
		stream_series = self._resolve_stream_boundary_series()
		stream_support_mask = self._stream_chd_support_mask(stream_series)
		spd = {kper: [] for kper in range(int(self.nper))}
		if stream_series is None or not np.any(stream_support_mask):
			return spd, stream_support_mask

		cell_ids = np.where(stream_support_mask)[0]
		for kper, head in enumerate(np.asarray(stream_series, dtype=float)):
			period_cells: list[list[float]] = []
			for ilay in range(int(self.nlay)):
				for cid in cell_ids.tolist():
					period_cells.append([ilay, cid, float(head)])
			spd[kper] = period_cells
		return spd, stream_support_mask

	def _build_side_boundary_chd_spd(self) -> dict[int, list[list[float]]]:
		bc = self._boundary_conditions_mapping()
		dem_mask_flat = np.asarray(self.dem_mask, dtype=bool).reshape(-1)
		spd = {kper: {} for kper in range(int(self.nper))}
		for bc_id in ("west_side", "east_side", "north_side", "south_side"):
			if not self._is_bc_active(bc_id):
				continue
			boundary = bc.get(bc_id)
			if boundary is None:
				continue
			series = self._resolve_side_boundary_series(boundary=boundary, bc_id=bc_id)
			for kper, head in enumerate(series):
				for ilay in range(int(self.nlay)):
					for cid in self._boundary_support_cell_ids(boundary=boundary, bc_id=bc_id):
						if bool(dem_mask_flat[cid]):
							continue
						spd[kper][(ilay, cid)] = [ilay, cid, float(head)]
		return {kper: list(period_map.values()) for kper, period_map in spd.items()}

	def _resolve_drainage_conductance_series(self) -> np.ndarray | None:
		if not self._is_bc_active("drainage"):
			return None
		boundary = self._boundary_conditions_mapping().get("drainage")
		if boundary is None:
			return None
		forcing = getattr(boundary, "forcing", None)
		if forcing is not None:
			raw_values = resolve_period_values_from_forcing(
					forcing=forcing,
					simulation_window=None if self.time_grid is None else self.time_grid.window,
					nper=int(self.nper),
					label="flow.bc.drainage.forcing",
				)
			return self._coerce_conductance_series_to_m2_per_s(
				values=raw_values,
				units=self._forcing_units(
					forcing,
					fallback=getattr(boundary, "units", "m2/s"),
				),
				label="flow.bc.drainage.forcing",
			)
		return self._coerce_conductance_series_to_m2_per_s(
			values=self._boundary_period_series(
			value=getattr(boundary, "value", None),
			label="flow.bc.drainage.value",
			),
			units=getattr(boundary, "units", "m2/s"),
			label="flow.bc.drainage.value",
		)

	@staticmethod
	def _copy_runtime_payload(payload: object) -> object:
		"""Return a detached copy of one runtime payload when possible."""
		if isinstance(payload, Mapping):
			return {
				key: Modflow6._copy_runtime_payload(value)
				for key, value in payload.items()
			}
		if hasattr(payload, "copy"):
			try:
				return payload.copy()
			except Exception:
				pass
		return payload

	@staticmethod
	def _calibration_runtime_reuse_enabled(
		flow_runtime_overrides: Mapping[str, object] | None,
	) -> bool:
		"""Return ``True`` when calibration asks for one reusable MF6 runtime."""
		return bool(
			isinstance(flow_runtime_overrides, Mapping)
			and flow_runtime_overrides.get("reuse_solver_model", False)
		)

	def _runtime_reuse_signature(
		self,
		*,
		flow: object,
		domain: object,
		options: ModflowPreprocessOptions,
		mesh_planar: object | None,
		mesh_support: object | None,
	) -> tuple[object, ...]:
		"""Capture the static runtime structure that must remain stable."""
		time_grid = getattr(options, "time_grid", None)
		return (
			id(flow),
			id(domain),
			id(mesh_planar),
			id(mesh_support),
			id(time_grid),
			str(self.flow_regime or ""),
		)

	def _can_refresh_runtime_reuse(
		self,
		*,
		flow: object,
		domain: object,
		options: ModflowPreprocessOptions,
		mesh_planar: object | None,
		mesh_support: object | None,
		flow_runtime_overrides: Mapping[str, object] | None,
	) -> bool:
		"""Return ``True`` when a cached runtime can be refreshed in place."""
		if not self._calibration_runtime_reuse_enabled(flow_runtime_overrides):
			return False
		if getattr(self, "sim", None) is None or getattr(self, "gwf", None) is None:
			return False
		signature = self._runtime_reuse_signature(
			flow=flow,
			domain=domain,
			options=options,
			mesh_planar=mesh_planar,
			mesh_support=mesh_support,
		)
		return signature == getattr(self, "_calibration_runtime_reuse_signature", None)

	def _build_drain_stress_period_data(
		self,
		*,
		solver_mesh,
		drainage_cond_series: np.ndarray,
		ocean_support_mask: np.ndarray,
		stream_support_mask: np.ndarray,
	) -> dict[int, list[list[float]]]:
		"""Build DRN stress-period data, including hk-scaled fallback conductance."""
		drn_spd = {}
		top_flat = solver_mesh.top
		dem_mask_flat = np.asarray(self.dem_mask, dtype=bool).reshape(-1)
		ocean_mask_flat = np.asarray(ocean_support_mask, dtype=bool).reshape(-1)
		stream_mask_flat = np.asarray(stream_support_mask, dtype=bool).reshape(-1)
		cell_areas = solver_mesh.cell_areas()
		for kper in range(int(self.nper)):
			period_cells = []
			configured_cond_value = float(drainage_cond_series[kper])
			for cid in range(int(self.ncpl)):
				if dem_mask_flat[cid] or ocean_mask_flat[cid] or stream_mask_flat[cid]:
					continue
				if configured_cond_value > 0.0:
					cond_value = max(configured_cond_value, 1e-12)
				else:
					cond_value = max(float(self.hk[0, cid]) * float(cell_areas[cid]), 1e-12)
				period_cells.append([0, cid, float(top_flat[cid]), cond_value])
			drn_spd[kper] = period_cells
		return drn_spd

	def _refresh_reused_runtime_property_packages(
		self,
		*,
		flow_runtime_overrides: Mapping[str, object] | None,
	) -> tuple[str, ...]:
		"""Update only runtime-varying hydraulic packages on a reused MF6 object."""
		flow_params = resolve_flow_property_arrays(
			flow=self.flow,
			domain=self.domain,
			solver_mesh=self.solver_mesh,
			planar_mesh=self.runtime_mesh_planar,
			required_properties=resolve_required_flow_properties(flow_regime=self.flow_regime),
			optional_fill_values={"Sy": 0.0, "Ss": 0.0},
			runtime_property_overrides=flow_runtime_overrides,
		)
		self.hk = self.solver_mesh.flatten_from_grid(flow_params["hk"])
		self.sy = self.solver_mesh.flatten_from_grid(flow_params["sy"])
		self.ss = self.solver_mesh.flatten_from_grid(flow_params["ss"])

		updated_packages: list[str] = []
		if getattr(self, "npf", None) is not None:
			self.npf.k.set_data(self.hk)
			self.npf.k33.set_data(
				self.hk
				/ max(
					float(
						getattr(
							getattr(self.modflow_config, "process_specific", object()),
							"vka",
							1.0,
						)
					),
					1e-12,
				)
			)
			updated_packages.append("npf")
		if getattr(self, "sto", None) is not None:
			self.sto.sy.set_data(self.sy)
			self.sto.ss.set_data(self.ss)
			updated_packages.append("sto")

		drainage_cond_series = getattr(self, "_drainage_cond_series", None)
		if (
			getattr(self, "drn", None) is not None
			and drainage_cond_series is not None
			and bool(getattr(self, "_drainage_uses_hk", False))
		):
			drn_spd = self._build_drain_stress_period_data(
				solver_mesh=self.solver_mesh,
				drainage_cond_series=drainage_cond_series,
				ocean_support_mask=np.asarray(
					getattr(self, "_ocean_support_mask", np.zeros(int(self.ncpl), dtype=bool)),
					dtype=bool,
				),
				stream_support_mask=np.asarray(
					getattr(self, "_stream_support_mask", np.zeros(int(self.ncpl), dtype=bool)),
					dtype=bool,
				),
			)
			self.drn.stress_period_data.set_data(drn_spd)
			updated_packages.append("drn")

		return tuple(updated_packages)

	@staticmethod
	def _sanitize_numeric_payload(payload: object) -> object:
		return mf6_flow_adapter.sanitize_numeric_payload(payload)

	@staticmethod
	def _payload_has_negative_values(payload: object) -> bool:
		return mf6_flow_adapter.payload_has_negative_values(payload)

	@staticmethod
	def _clip_negative_payload(payload: object) -> object:
		return mf6_flow_adapter.clip_negative_payload(payload)

	def _extract_evt_payload_2d(
		self,
		rch_data: Mapping[int, object],
		negative_to_evt: bool,
	) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray] | None]:
		return mf6_flow_adapter.extract_evt_payload_2d(rch_data, negative_to_evt)

	def _series_payload_value(self, payload: object, kper: int, *, first_clim: object) -> float:
		return mf6_flow_adapter.series_payload_value(payload, kper, first_clim=first_clim)

	def _extract_evt_payload(
		self,
		payload: object,
		negative_to_evt: bool,
	) -> tuple[object, dict[int, object] | None]:
		return mf6_flow_adapter.extract_evt_payload(self, payload, negative_to_evt)

	def _bind_recharge_from_flow(self) -> None:
		mf6_flow_adapter.bind_recharge_from_flow(self)

	def _bind_heterogeneous_recharge(self, recharge_cfg: object) -> None:
		mf6_flow_adapter.bind_heterogeneous_recharge(self, recharge_cfg)

	def _resolve_deferred_heterogeneous_recharge(self) -> None:
		mf6_flow_adapter.resolve_deferred_heterogeneous_recharge(self)

	def _scalar_to_flat(self, value: float) -> np.ndarray:
		return mf6_flow_adapter.scalar_to_flat(self, value)

	def _as_recharge_flat(self, value: object, *, kper: int | None = None) -> np.ndarray:
		return mf6_flow_adapter.as_recharge_flat(self, value, kper=kper)

	def _series_like_to_scalar(self, kper: int) -> float:
		return mf6_flow_adapter.series_like_to_scalar(self, kper)

	def _recharge_to_spd(self) -> dict[int, np.ndarray]:
		return mf6_flow_adapter.recharge_to_spd(self)

	def _empty_recharge_aux(self) -> dict[int, list[np.ndarray]]:
		return mf6_flow_adapter.empty_recharge_aux(self)

	def _finalize_pending_recharge_evt(self) -> None:
		mf6_flow_adapter.finalize_pending_recharge_evt(self)

	def _resolve_rewet_npf_options(
		self,
		solver_mesh,
	) -> tuple[list[object] | None, np.ndarray | None]:
		return mf6_flow_adapter.resolve_rewet_npf_options(self, solver_mesh)

	def _build_evt_stress_period_data(
		self,
		solver_mesh,
		*,
		ocean_support_mask: np.ndarray,
		stream_support_mask: np.ndarray,
	) -> dict[int, list[list[float]]] | None:
		return mf6_flow_adapter.build_evt_stress_period_data(
			self,
			solver_mesh,
			ocean_support_mask=ocean_support_mask,
			stream_support_mask=stream_support_mask,
		)

	def pre_processing(
		self,
		flow: object,
		domain: object,
		options: ModflowPreprocessOptions | None = None,
		*,
		mesh_planar: object | None = None,
		mesh_support: object | None = None,
		flow_runtime_overrides: Mapping[str, object] | None = None,
	):
		self.flow = flow
		self.domain = domain
		self.runtime_mesh_planar = mesh_planar
		self.runtime_mesh_support = mesh_support
		active_options = self.preprocess_options if options is None else options
		self._apply_preprocess_options(active_options)
		self._validate_pre_processing_inputs()
		self._bind_recharge_from_flow()
		self._calibration_raw_output_payload_cache = {}

		self.flow_regime = self._resolve_flow_regime() or "transient"
		runtime_reuse_signature = self._runtime_reuse_signature(
			flow=flow,
			domain=domain,
			options=active_options,
			mesh_planar=mesh_planar,
			mesh_support=mesh_support,
		)
		if self._can_refresh_runtime_reuse(
			flow=flow,
			domain=domain,
			options=active_options,
			mesh_planar=mesh_planar,
			mesh_support=mesh_support,
			flow_runtime_overrides=flow_runtime_overrides,
		):
			self._runtime_dirty_packages = self._refresh_reused_runtime_property_packages(
				flow_runtime_overrides=flow_runtime_overrides,
			)
			self._calibration_runtime_reuse_signature = runtime_reuse_signature
			return
		launcher_time_grid = self.time_grid
		temporal = build_temporal_discretization_from_time_grid(
			time_grid=launcher_time_grid,
			flow_regime=self.flow_regime,
			firstpersteady=bool(getattr(getattr(self.modflow_config, "tgrid", None), "firstpersteady", True)),
		)
		self.perlen = temporal.perlen
		self.nper = temporal.nper
		self.nstp = temporal.nstp
		self.steady = temporal.steady
		time_units = "seconds"
		self._finalize_pending_recharge_evt()

		self.grid_ctx = build_spatial_discretization(
			domain=self.domain,
			sgrid_config=getattr(self.modflow_config, "sgrid", None),
			runtime_planar_mesh=self.runtime_mesh_planar,
			runtime_mesh_support=self.runtime_mesh_support,
		)
		solver_mesh = self.grid_ctx.solver_mesh
		self.solver_mesh = solver_mesh
		self.top_elevation = solver_mesh.top  # (ncpl,)
		self.inactive_mask = solver_mesh.inactive_mask[0]  # (ncpl,)
		self.nlay = solver_mesh.nlay
		self.ncpl = solver_mesh.n_cells
		if solver_mesh.is_structured:
			self.nrow = solver_mesh.nrow
			self.ncol = solver_mesh.ncol
		self.cell_area = float(self.grid_ctx.grid.cell_area)
		self.resolution = float(self.grid_ctx.grid.characteristic_length)
		self.dem = self.top_elevation  # flat (ncpl,)
		self.dem_mask = self.inactive_mask  # flat (ncpl,)
		self.dem_watershed_path = self._write_solver_grid_template()

		# Deferred heterogeneous recharge: discretize now that solver_mesh is built.
		self._resolve_deferred_heterogeneous_recharge()

		flow_params = resolve_flow_property_arrays(
			flow=self.flow,
			domain=self.domain,
			solver_mesh=solver_mesh,
			planar_mesh=self.runtime_mesh_planar,
			required_properties=resolve_required_flow_properties(flow_regime=self.flow_regime),
			optional_fill_values={"Sy": 0.0, "Ss": 0.0},
			runtime_property_overrides=flow_runtime_overrides,
		)
		# Flatten property arrays to (nlay, ncpl).
		self.hk = solver_mesh.flatten_from_grid(flow_params["hk"])
		self.sy = solver_mesh.flatten_from_grid(flow_params["sy"])
		self.ss = solver_mesh.flatten_from_grid(flow_params["ss"])

		runtime = getattr(self.modflow_config, "runtime", None)
		sim_name = self.model_name_mf6
		self.sim = flopy.mf6.MFSimulation(sim_name=sim_name, sim_ws=self.full_path, exe_name=self.exe)
		# TGrid/TMesh fields consumed here:
		# - perlen (stress-period length),
		# - nstp (time-step count),
		# - itmuni (time_units metadata).
		# Current implementation keeps MF6 TDIS tsmult fixed to 1.0.
		self.tdis = flopy.mf6.ModflowTdis(
			self.sim,
			nper=int(self.nper),
			perioddata=[(float(self.perlen[i]), int(self.nstp[i]), 1.0) for i in range(int(self.nper))],
			time_units=time_units,
		)
		self.ims = flopy.mf6.ModflowIms(
			self.sim,
			print_option="SUMMARY" if getattr(runtime, "mf_verbose", False) else "NONE",
			complexity=getattr(runtime, "mf6_ims_complexity", "COMPLEX"),
			outer_dvclose=float(getattr(runtime, "mf6_outer_dvclose", 1e-4)),
			inner_dvclose=float(getattr(runtime, "mf6_inner_dvclose", 1e-4)),
			outer_maximum=int(getattr(runtime, "mf6_outer_maximum", 500)),
			inner_maximum=int(getattr(runtime, "mf6_inner_maximum", 500)),
			filename=f"{self.model_name_mf6}_gwf.ims",
			pname="IMS_GWF",
		)
		self.gwf = flopy.mf6.ModflowGwf(
			self.sim,
			modelname=self.model_name_mf6,
			save_flows=True,
			print_input=getattr(runtime, "mf_verbose", False),
			print_flows=getattr(runtime, "mf_verbose", False),
		)
		self.sim.register_ims_package(self.ims, [self.gwf.name])
		# Build idomain as flat (nlay, ncpl) — DISV convention.
		idomain = np.where(solver_mesh.inactive_mask, 0, 1).astype(int)  # (nlay, ncpl)

		disv_kwargs = solver_mesh.to_disv_kwargs()
		self.dis = flopy.mf6.ModflowGwfdisv(
			self.gwf,
			nlay=solver_mesh.nlay,
			**disv_kwargs,
			idomain=idomain,
			xorigin=float(solver_mesh.xoffset),
			yorigin=float(solver_mesh.yoffset),
			length_units="METERS",
		)

		strt = self._build_start_heads(solver_mesh)
		self.ic = flopy.mf6.ModflowGwfic(self.gwf, strt=strt)
		ocean_chd_spd, ocean_support_mask = self._build_ocean_boundary_chd_spd()
		stream_chd_spd, stream_support_mask = self._build_stream_boundary_chd_spd()
		self._ocean_support_mask = np.asarray(ocean_support_mask, dtype=bool).copy()
		self._stream_support_mask = np.asarray(stream_support_mask, dtype=bool).copy()
		rewet_record, wetdry = self._resolve_rewet_npf_options(solver_mesh)

		self.npf = flopy.mf6.ModflowGwfnpf(
			self.gwf,
			icelltype=np.ones((self.nlay,), dtype=int),
			k=self.hk,
			k33=self.hk / max(float(getattr(getattr(self.modflow_config, "process_specific", object()), "vka", 1.0)), 1e-12),
			rewet_record=rewet_record,
			wetdry=wetdry,
			save_specific_discharge=True,
			save_saturation=True,
		)
		self.sto = flopy.mf6.ModflowGwfsto(
			self.gwf,
			sy=self.sy,
			ss=self.ss,
			iconvert=np.ones((self.nlay,), dtype=int),
			steady_state={0: bool(self.steady[0])},
			transient={i: not bool(self.steady[i]) for i in range(int(self.nper))},
		)

		self.rch_spd = self._recharge_to_spd()
		self.rch = flopy.mf6.ModflowGwfrcha(
			self.gwf,
			recharge=self.rch_spd,
			auxiliary=["CONCENTRATION"],
			aux=self._empty_recharge_aux(),
			pname="RCHA",
		)
		evt_spd = self._build_evt_stress_period_data(
			solver_mesh,
			ocean_support_mask=ocean_support_mask,
			stream_support_mask=stream_support_mask,
		)
		if evt_spd is not None:
			maxbound = max((len(period_cells) for period_cells in evt_spd.values()), default=0)
			self.evt = flopy.mf6.ModflowGwfevt(
				self.gwf,
				stress_period_data=evt_spd,
				maxbound=maxbound,
				save_flows=True,
			)

		drainage_cond_series = self._resolve_drainage_conductance_series()
		self._drainage_cond_series = (
			None
			if drainage_cond_series is None
			else np.asarray(drainage_cond_series, dtype=float).copy()
		)
		self._drainage_uses_hk = bool(
			drainage_cond_series is not None
			and np.any(np.asarray(drainage_cond_series, dtype=float) <= 0.0)
		)
		if drainage_cond_series is not None:
			drn_spd = self._build_drain_stress_period_data(
				solver_mesh=solver_mesh,
				drainage_cond_series=np.asarray(drainage_cond_series, dtype=float),
				ocean_support_mask=np.asarray(ocean_support_mask, dtype=bool),
				stream_support_mask=np.asarray(stream_support_mask, dtype=bool),
			)
			self.drn = flopy.mf6.ModflowGwfdrn(self.gwf, stress_period_data=drn_spd, save_flows=True)

		side_chd_spd = self._build_side_boundary_chd_spd()
		chd_spd = {}
		for kper in range(int(self.nper)):
			period_map: dict[tuple[int, int], list[float]] = {}
			for entry in ocean_chd_spd.get(kper, []):
				period_map[(int(entry[0]), int(entry[1]))] = entry
			for entry in stream_chd_spd.get(kper, []):
				period_map[(int(entry[0]), int(entry[1]))] = entry
			for entry in side_chd_spd.get(kper, []):
				period_map[(int(entry[0]), int(entry[1]))] = entry
			chd_spd[kper] = list(period_map.values())
		if any(len(v) > 0 for v in chd_spd.values()):
			self.chd = flopy.mf6.ModflowGwfchd(self.gwf, stress_period_data=chd_spd, save_flows=True)

		wel_spd = self._build_well_stress_period_data(int(self.nper))
		if any(len(v) > 0 for v in wel_spd.values()):
			self.wel = flopy.mf6.ModflowGwfwel(self.gwf, stress_period_data=wel_spd, save_flows=True)

		self.oc = flopy.mf6.ModflowGwfoc(
			self.gwf,
			head_filerecord=f"{self.model_name}.hds",
			budget_filerecord=f"{self.model_name}.cbc",
			saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
			printrecord=[("HEAD", "LAST")],
		)
		self._runtime_dirty_packages = ()
		self._calibration_runtime_reuse_signature = runtime_reuse_signature

	def processing(self, options: ModflowRunOptions | None = None):
		if options is None:
			options = ModflowRunOptions()
		elif not isinstance(options, ModflowRunOptions):
			raise TypeError("processing options must be ModflowRunOptions")

		if options.write_model:
			dirty_packages = tuple(getattr(self, "_runtime_dirty_packages", ()) or ())
			if dirty_packages:
				for package_name in dirty_packages:
					package = getattr(self, str(package_name), None)
					if package is None:
						continue
					package.write()
				self._runtime_dirty_packages = ()
			else:
				self.sim.write_simulation(silent=not options.verbose)

		success_model = False
		if options.run_model:
			success_model, _ = self.sim.run_simulation(silent=not options.verbose)
		return success_model

	def post_processing(self, options: ModflowPostprocessOptions | None = None):
		mf6_postprocess.run_flow_post_processing(self, options)


class Modflow6Transport:
	"""Transport solver based on MODFLOW 6 GWT and `transport.modflow6gwt.parameters`."""

	def __init__(
		self,
		domain: object,
		transport: object,
		model_modflow: object,
		model_folder: str = "HydroModPy_outputs",
		model_name: str = "Default_modflow6",
		suffix_name: str = "_gwt",
		bin_path: str = "bin",
		**kwargs,
	):
		self.domain = domain
		self.transport = transport
		self.model_modflow = model_modflow
		self.model_folder = model_folder
		self.model_name = model_name
		self.suffix_name = suffix_name
		self.model_name_mt = model_name + suffix_name
		self.model_name_mt_mf6 = _mf6_safe_name(self.model_name_mt)
		self.full_path = os.path.join(model_folder, model_name)
		self.exe = getattr(model_modflow, "exe", "mf6")

		conc_params = {}
		comp = transport.modflow6gwt
		if isinstance(getattr(comp, "parameters", None), Mapping):
			conc_params = dict(comp.parameters)
		conc_params.update(kwargs)
		conc_params.update(
			build_concentration_runtime_overrides(
				conc_params,
				model_modflow,
			)
		)

		self.spc_name = conc_params.get("spc_name", "NO3")
		self.sconc_init = conc_params.get("sconc_init", 0.0)
		self.sconc_input = conc_params.get("sconc_input", 0.0)
		self.disp_long = float(conc_params.get("disp_long", 0.0))
		self.disp_transh = float(conc_params.get("disp_transh", 0.0))
		self.disp_transv = float(conc_params.get("disp_transv", 0.0))
		self.diffu_coeff = float(conc_params.get("diffu_coeff", 0.0))
		self.react_order = conc_params.get("react_order", None)
		self.rate_decay = conc_params.get("rate_decay", 0.0)
		self.plot_conc = bool(conc_params.get("plot_conc", True))

	def _build_crch(self) -> dict[int, np.ndarray]:
		nper = int(self.model_modflow.nper)
		ncpl = int(self.model_modflow.ncpl)
		if isinstance(self.sconc_input, dict):
			out = {}
			for k in range(nper):
				arr = self.sconc_input.get(k)
				if arr is None:
					arr = np.zeros(ncpl, dtype=float)
				out[k] = np.asarray(arr, dtype=float).reshape(-1)
			return out
		val = float(self.sconc_input)
		return {k: np.full(ncpl, val, dtype=float) for k in range(nper)}

	def _build_crch_aux(self) -> dict[int, list[np.ndarray]]:
		crch = self._build_crch()
		return {k: [np.asarray(v, dtype=float)] for k, v in crch.items()}

	def pre_processing(self):
		sim = self.model_modflow.sim
		self.gwf = self.model_modflow.gwf
		self.ims = flopy.mf6.ModflowIms(
			sim,
			print_option="SUMMARY",
			complexity="COMPLEX",
			filename=f"{self.model_name_mt_mf6}.ims",
			pname="IMS_GWT",
		)
		self.gwt = flopy.mf6.ModflowGwt(sim, modelname=self.model_name_mt_mf6, save_flows=True)
		sim.register_ims_package(self.ims, [self.gwt.name])
		if hasattr(self.model_modflow, "ims") and self.model_modflow.ims is not None:
			sim.name_file.solutiongroup.set_data(
				[
					("ims6", self.model_modflow.ims.filename, self.gwf.name),
					("ims6", self.ims.filename, self.gwt.name),
				],
				key=0,
			)

		disv_kwargs = self.model_modflow.solver_mesh.to_disv_kwargs()
		self.gwtdis = flopy.mf6.ModflowGwtdisv(
			self.gwt,
			nlay=self.model_modflow.nlay,
			**disv_kwargs,
		)
		self.gwtic = flopy.mf6.ModflowGwtic(self.gwt, strt=self.sconc_init)
		self.adv = flopy.mf6.ModflowGwtadv(self.gwt, scheme="upstream")
		self.dsp = flopy.mf6.ModflowGwtdsp(
			self.gwt,
			alh=self.disp_long,
			ath1=self.disp_long * self.disp_transh,
			atv=self.disp_long * self.disp_transv,
			diffc=self.diffu_coeff,
		)

		decay = self.rate_decay if self.react_order in {0, 1} else None
		self.mst = flopy.mf6.ModflowGwtmst(
			self.gwt,
			porosity=self.model_modflow.sy,
			first_order_decay=bool(self.react_order == 1),
			decay=decay,
		)

		if not hasattr(self.model_modflow, "rch") or self.model_modflow.rch is None:
			raise RuntimeError("Modflow6Transport requires an existing GWF recharge package.")
		self.model_modflow.rch.aux.set_data(self._build_crch_aux())
		self.ssm = flopy.mf6.ModflowGwtssm(self.gwt, sources=[("RCHA", "AUX", "CONCENTRATION")])

		self.gwfgwt = flopy.mf6.ModflowGwfgwt(
			sim,
			exgtype="GWF6-GWT6",
			exgmnamea=self.gwf.name,
			exgmnameb=self.gwt.name,
		)
		self.oc = flopy.mf6.ModflowGwtoc(
			self.gwt,
			concentration_filerecord=f"{self.model_name_mt}.ucn",
			budget_filerecord=f"{self.model_name_mt}.cbc",
			saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
		)

	def processing(self, write_model: bool = True, run_model: bool = False, verbose: bool = True):
		if write_model:
			self.model_modflow.sim.write_simulation(silent=not verbose)
		success = False
		if run_model:
			success, _ = self.model_modflow.sim.run_simulation(silent=not verbose)
		return success

	def _resolve_postprocess_options(
		self,
		*,
		export_all_tif: bool,
		options: ModflowPostprocessOptions | None,
	) -> ModflowPostprocessOptions:
		"""Resolve transport post-processing options from explicit or inherited flow settings."""
		if options is not None and not isinstance(options, ModflowPostprocessOptions):
			raise TypeError("transport post_processing options must be ModflowPostprocessOptions")

		resolved = options
		if resolved is None:
			inherited = getattr(self.model_modflow, "last_postprocess_options", None)
			if isinstance(inherited, ModflowPostprocessOptions):
				resolved = inherited
		if resolved is None:
			return ModflowPostprocessOptions(export_all_tif=bool(export_all_tif))
		if bool(getattr(resolved, "export_all_tif", False)) == bool(export_all_tif):
			return resolved
		return replace(resolved, export_all_tif=bool(export_all_tif))

	def post_processing(
		self,
		model_mt3dms: object,
		concentration_seepage: bool = True,
		mass_seepage: bool = True,
		mass_accumulated: bool = False,
		export_all_tif: bool = False,
		options: ModflowPostprocessOptions | None = None,
	):
		mf6_postprocess.run_transport_post_processing(
			self,
			model_mt3dms,
			concentration_seepage=concentration_seepage,
			mass_seepage=mass_seepage,
			mass_accumulated=mass_accumulated,
			export_all_tif=export_all_tif,
			options=options,
		)

