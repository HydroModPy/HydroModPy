"""MODFLOW 6 flow and transport solvers aligned with HydroModPy workflow APIs."""

from __future__ import annotations

import os
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real

import flopy
import flopy.utils.binaryfile as bf
import numpy as np
import rasterio
from flopy.utils import postprocessing as pp

from hydromodpy.process.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow_common import (
	masstransfer,
	SolverGridContext,
	SolverRoutingContext,
	build_solver_routing_context,
	write_grid_array_to_raster,
)
from hydromodpy.solver import Solver
from hydromodpy.solver.modflow_nwt.modflow import (
	ModflowPostprocessOptions,
	ModflowPreprocessOptions,
	ModflowRunOptions,
)
from hydromodpy.solver.modflow_nwt.modflow.discretization import (
	build_spatial_discretization,
	build_temporal_discretization_from_time_grid,
)
from hydromodpy.solver.modflow6.modflow6_config import (
	Modflow6Config,
	_coerce_modflow6_config,
)
from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
	resolve_required_flow_properties,
	resolve_flow_property_arrays,
)
from hydromodpy.solver.modflow_common.runtime_arrays import (
	build_concentration_runtime_overrides,
)
from hydromodpy.support.units import (
	convert_payload_to_m,
	convert_payload_to_m_per_s,
	factor_to_m2_per_s,
	normalize_length_unit,
)
from hydromodpy.support.units.volumetric_flow import (
	convert_to_m3_per_s,
	normalize_m3_per_s_unit,
)
from hydromodpy.support.tools import get_logger, toolbox

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

		self.resolution = geographic.dem_res
		self.xul = geographic.xmin
		self.yul = geographic.ymax
		self.sink = getattr(geographic, "depressions_data", None)

		self.preprocess_options = preprocess_options or ModflowPreprocessOptions()
		self._apply_preprocess_options(self.preprocess_options)

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

	def _build_well_stress_period_data(self, n_stress_periods: int) -> dict[int, list[list[float]]]:
		if n_stress_periods <= 0 or self.flow is None:
			return {}

		active = getattr(self.flow, "active_sinks_sources", [])
		if "wells" not in active:
			return {}

		sinks_sources = getattr(self.flow, "sinks_sources", {})
		if not isinstance(sinks_sources, Mapping):
			return {}

		wells = sinks_sources.get("wells", {})
		if wells is None:
			return {}
		if not isinstance(wells, Mapping):
			raise TypeError("flow.sinks_sources['wells'] must be a mapping of well ids to payloads.")
		if len(wells) == 0:
			return {}
		grid = None if self.grid_ctx is None else self.grid_ctx.grid

		normalized_wells: list[tuple[tuple[int, int], np.ndarray]] = []
		for well_id, raw_well_payload in wells.items():
			cell_payload = getattr(raw_well_payload, "cell", None)
			flux_payload = getattr(raw_well_payload, "flux", None)
			forcing_payload = getattr(raw_well_payload, "forcing", None)
			if cell_payload is None and isinstance(raw_well_payload, Mapping):
				cell_payload = raw_well_payload.get("cell")
				flux_payload = raw_well_payload.get("flux")
				forcing_payload = raw_well_payload.get("forcing")
			if cell_payload is None and hasattr(raw_well_payload, "resolve_cell"):
				if grid is None:
					raise ValueError(
						f"flow.sinks_sources.wells.{well_id} uses coordinate-based addressing "
						"but solver grid geometry is unavailable."
					)
				cell_payload = raw_well_payload.resolve_cell(grid)
			if cell_payload is None or (flux_payload is None and forcing_payload is None):
				continue

			cell_seq = list(cell_payload)
			if len(cell_seq) != 3:
				continue
			cell = self._well_cell_to_disv(int(cell_seq[0]), int(cell_seq[1]), int(cell_seq[2]))

			if forcing_payload is not None:
				raw_values = resolve_period_values_from_forcing(
					forcing=forcing_payload,
					simulation_window=None if self.time_grid is None else self.time_grid.window,
					nper=int(n_stress_periods),
					label=f"flow.sinks_sources.wells.{well_id}.forcing",
				)
				fallback_units = (
					raw_well_payload.get("units", "m3/s")
					if isinstance(raw_well_payload, Mapping)
					else getattr(raw_well_payload, "units", "m3/s")
				)
				canonical_units = normalize_m3_per_s_unit(
					self._forcing_units(
						forcing_payload,
						fallback=fallback_units,
					)
				)
				flux_vector = np.asarray(
					[
						convert_to_m3_per_s(
							value,
							unit=canonical_units,
							label=f"flow.sinks_sources.wells.{well_id}.forcing[{idx}]",
						)
						for idx, value in enumerate(raw_values)
					],
					dtype=float,
				)
			elif isinstance(flux_payload, Real) and not isinstance(flux_payload, bool):
				flux_vector = np.full((n_stress_periods,), float(flux_payload), dtype=float)
			else:
				raw_flux_seq = list(flux_payload)
				parsed = np.asarray(raw_flux_seq, dtype=float)
				if parsed.size == 1:
					flux_vector = np.full((n_stress_periods,), float(parsed[0]), dtype=float)
				elif parsed.size >= n_stress_periods:
					flux_vector = parsed[:n_stress_periods].astype(float)
				else:
					flux_vector = np.full((n_stress_periods,), float(parsed[-1]), dtype=float)
					flux_vector[: parsed.size] = parsed
			normalized_wells.append((cell, flux_vector))

		spd: dict[int, list[list[float]]] = {}
		for t in range(n_stress_periods):
			spd[t] = [[cell[0], cell[1], float(flux_vector[t])] for cell, flux_vector in normalized_wells]
		return spd

	@staticmethod
	def _is_scalar_number(value: object) -> bool:
		return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)

	def _boundary_conditions_mapping(self) -> Mapping[str, object]:
		boundary_conditions = getattr(self.flow, "boundary_conditions", {})
		if not isinstance(boundary_conditions, Mapping):
			raise TypeError("flow.boundary_conditions must be a mapping")
		return boundary_conditions

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
		forcing = getattr(boundary, "forcing", None)
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
					fallback=getattr(boundary, "units", "m"),
				),
				label=f"flow.bc.{bc_id}.forcing",
			)
		return self._coerce_length_series_to_m(
			values=self._boundary_period_series(
			value=getattr(boundary, "value", None),
			label=f"flow.bc.{bc_id}.value",
			),
			units=getattr(boundary, "units", "m"),
			label=f"flow.bc.{bc_id}.value",
		)

	def _side_boundary_cell_ids(self, bc_id: str) -> list[int]:
		"""Return flat cell IDs on one side of a structured grid."""
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
			cell_ids = self._side_boundary_cell_ids(bc_id)
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
		return self._apply_side_boundary_start_heads(strt)

	def _resolve_ocean_boundary_series(self) -> np.ndarray | None:
		if not self._is_bc_active("ocean"):
			return None
		boundary = self._boundary_conditions_mapping().get("ocean")
		if boundary is None:
			return None
		forcing = getattr(boundary, "forcing", None)
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
					fallback=getattr(boundary, "units", "m"),
				),
				label="flow.bc.ocean.forcing",
			)
		return self._coerce_length_series_to_m(
			values=self._boundary_period_series(
			value=getattr(boundary, "value", None),
			label="flow.bc.ocean.value",
			),
			units=getattr(boundary, "units", "m"),
			label="flow.bc.ocean.value",
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
				for ilay, cid in self._iter_side_boundary_cells(bc_id):
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
	def _sanitize_numeric_payload(payload: object) -> object:
		"""Replace unsupported/invalid numeric payload values by finite MF6-safe values."""
		if payload is None:
			return 0.0
		if isinstance(payload, Mapping):
			return {
				key: Modflow6._sanitize_numeric_payload(value)
				for key, value in payload.items()
			}
		if isinstance(payload, Real) and not isinstance(payload, bool):
			scalar = float(payload)
			return 0.0 if not np.isfinite(scalar) else scalar
		if hasattr(payload, "replace") and hasattr(payload, "fillna"):
			series = payload.copy()
			series = series.astype(float)
			return series.replace([np.inf, -np.inf], np.nan).fillna(0.0)

		arr = np.asarray(payload, dtype=float)
		if arr.ndim == 0:
			scalar = float(arr)
			return 0.0 if not np.isfinite(scalar) else scalar
		return np.nan_to_num(arr.astype(float, copy=False), nan=0.0, posinf=0.0, neginf=0.0)

	@staticmethod
	def _payload_has_negative_values(payload: object) -> bool:
		"""Return True when a recharge payload contains at least one negative value."""
		if isinstance(payload, Mapping):
			return any(Modflow6._payload_has_negative_values(value) for value in payload.values())
		if isinstance(payload, Real) and not isinstance(payload, bool):
			return float(payload) < 0.0
		arr = np.asarray(payload, dtype=float)
		return bool(np.any(arr < 0.0))

	@staticmethod
	def _clip_negative_payload(payload: object) -> object:
		"""Clip negative recharge values to zero for MF6 RCH compatibility."""
		if isinstance(payload, Mapping):
			return {
				key: Modflow6._clip_negative_payload(value)
				for key, value in payload.items()
			}
		if isinstance(payload, Real) and not isinstance(payload, bool):
			return max(float(payload), 0.0)
		if hasattr(payload, "clip"):
			try:
				return payload.clip(lower=0.0)
			except TypeError:
				pass

		arr = np.asarray(payload, dtype=float)
		if arr.ndim == 0:
			return max(float(arr), 0.0)
		return np.maximum(arr, 0.0)

	def _bind_recharge_from_flow(self) -> None:
		"""Resolve recharge inputs from the canonical flow recharge configuration."""
		if self.recharge is not None:
			self.recharge = self._sanitize_numeric_payload(self.recharge)
			if self.first_clim is None:
				self.first_clim = "mean"
			return

		active = getattr(self.flow, "active_sinks_sources", [])
		if "recharge" not in active:
			self.recharge = 0.0
			if self.first_clim is None:
				self.first_clim = "mean"
			return

		sinks_sources = getattr(self.flow, "sinks_sources", {})
		recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None
		if recharge_cfg is None:
			self.recharge = 0.0
			if self.first_clim is None:
				self.first_clim = "mean"
			return

		# Heterogeneous path: gridded FieldRecords from data managers.
		het_source = getattr(recharge_cfg, "heterogeneous_source", None)
		if het_source is not None and getattr(het_source, "has_fields", False):
			self._bind_heterogeneous_recharge(recharge_cfg)
			return

		payload = self._copy_runtime_payload(getattr(recharge_cfg, "values", 0.0))
		payload = convert_payload_to_m_per_s(
			payload,
			unit=str(getattr(recharge_cfg, "units", "m/s")),
			label="flow.sinks_sources.recharge.values",
		)
		payload = self._sanitize_numeric_payload(payload)
		if bool(getattr(recharge_cfg, "negative_to_evt", False)) and self._payload_has_negative_values(payload):
			logger.info(
				"MF6 flow recharge clips negative values to 0.0; EVT routing is not yet implemented in this adapter"
			)
			payload = self._clip_negative_payload(payload)

		self.recharge = payload
		self.first_clim = getattr(
			recharge_cfg,
			"first_clim",
			self.first_clim if self.first_clim is not None else "mean",
		)

	def _bind_heterogeneous_recharge(self, recharge_cfg: object) -> None:
		"""Store heterogeneous source for deferred discretization.

		The actual discretization is performed in
		:meth:`_resolve_deferred_heterogeneous_recharge` after the
		structured grid is built.
		"""
		self._heterogeneous_recharge_source = recharge_cfg.heterogeneous_source
		self._heterogeneous_negative_to_evt = bool(
			getattr(recharge_cfg, "negative_to_evt", False)
		)
		self._heterogeneous_interpolation_method = getattr(
			recharge_cfg, "interpolation_method", "nearest"
		)
		self.recharge = 0.0  # placeholder; replaced after solver_mesh construction
		self.first_clim = getattr(
			recharge_cfg,
			"first_clim",
			self.first_clim if self.first_clim is not None else "mean",
		)

	def _resolve_deferred_heterogeneous_recharge(self) -> None:
		"""Discretize stored heterogeneous recharge after solver_mesh is available."""
		het_source = getattr(self, "_heterogeneous_recharge_source", None)
		if het_source is None:
			return

		from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_field_discretization import (
			discretize_fields_on_sgrid,
			discretize_points_on_sgrid,
		)

		sim_window = self.time_grid.window if self.time_grid is not None else None
		interp_method = getattr(self, "_heterogeneous_interpolation_method", "nearest")

		# Prefer fields; fall back to located points.
		if getattr(het_source, "has_fields", False):
			raw_arrays = discretize_fields_on_sgrid(
				load_result=het_source,
				sgrid=self.solver_mesh,
				nper=int(self.nper),
				simulation_window=sim_window,
				method=interp_method,
			)
		elif getattr(het_source, "has_points", False):
			raw_arrays = discretize_points_on_sgrid(
				load_result=het_source,
				sgrid=self.solver_mesh,
				nper=int(self.nper),
				simulation_window=sim_window,
				method=interp_method,
			)
		else:
			self._heterogeneous_recharge_source = None
			return

		# Clip negative values (MF6 RCH doesn't support negative recharge).
		if getattr(self, "_heterogeneous_negative_to_evt", False):
			logger.info(
				"MF6 heterogeneous recharge: clipping negative values to 0.0; "
				"EVT routing not yet implemented for 2D arrays."
			)
			for kper in raw_arrays:
				raw_arrays[kper] = np.maximum(raw_arrays[kper], 0.0)

		# _recharge_to_spd handles Mapping {kper: ndarray(ncpl,)}.
		self.recharge = raw_arrays
		self._heterogeneous_recharge_source = None

	def _scalar_to_flat(self, value: float) -> np.ndarray:
		"""Return flat (ncpl,) array filled with one scalar."""
		return np.full(int(self.ncpl), float(value), dtype=float)

	def _as_recharge_flat(self, value: object, *, kper: int | None = None) -> np.ndarray:
		"""Coerce one recharge value to a flat (ncpl,) array."""
		if isinstance(value, Real) and not isinstance(value, bool):
			return self._scalar_to_flat(float(value))

		arr = np.asarray(value, dtype=float)
		if arr.ndim == 0:
			return self._scalar_to_flat(float(arr))
		if arr.ndim == 1:
			if arr.size == 0:
				return np.zeros(int(self.ncpl), dtype=float)
			if arr.size == int(self.ncpl):
				return arr.astype(float)
			if kper is None:
				return self._scalar_to_flat(float(arr[-1]))
			idx = min(max(int(kper), 0), int(arr.size) - 1)
			return self._scalar_to_flat(float(arr[idx]))
		if arr.ndim == 2:
			flat = arr.ravel()
			if flat.size == int(self.ncpl):
				return flat.astype(float)
			if flat.size == 0:
				return np.zeros(int(self.ncpl), dtype=float)
			return self._scalar_to_flat(float(flat[-1]))
		if arr.ndim >= 3:
			if kper is None:
				kper = 0
			idx = min(max(int(kper), 0), int(arr.shape[0]) - 1)
			flat = np.asarray(arr[idx], dtype=float).ravel()
			if flat.size == int(self.ncpl):
				return flat
			if flat.size == 0:
				return np.zeros(int(self.ncpl), dtype=float)
			return self._scalar_to_flat(float(flat[-1]))

		return np.zeros(int(self.ncpl), dtype=float)

	def _series_like_to_scalar(self, kper: int) -> float:
		if kper == 0:
			if self.first_clim == "mean":
				arr = np.asarray(self.recharge, dtype=float)
				return float(np.nanmean(arr))
			if self.first_clim == "first":
				if hasattr(self.recharge, "iloc"):
					first = self.recharge.iloc[0]
					if isinstance(first, Real) and not isinstance(first, bool):
						return float(first)
					first_arr = np.asarray(first, dtype=float).ravel()
					return float(first_arr[0]) if first_arr.size else 0.0
				arr = np.asarray(self.recharge, dtype=float).ravel()
				return float(arr[0]) if arr.size else 0.0
			if isinstance(self.first_clim, Real) and not isinstance(self.first_clim, bool):
				return float(self.first_clim)

		if hasattr(self.recharge, "iloc"):
			idx = min(max(kper, 0), len(self.recharge) - 1)
			value = self.recharge.iloc[idx]
			if isinstance(value, Real) and not isinstance(value, bool):
				return float(value)
			value_arr = np.asarray(value, dtype=float).ravel()
			if value_arr.size:
				return float(value_arr[0])
			return 0.0

		arr = np.asarray(self.recharge, dtype=float).ravel()
		if arr.size == 0:
			return 0.0
		idx = min(max(kper, 0), int(arr.size) - 1)
		return float(arr[idx])

	def _recharge_to_spd(self) -> dict[int, np.ndarray]:
		spd: dict[int, np.ndarray] = {}
		if isinstance(self.recharge, Mapping):
			for kper in range(self.nper):
				arr = self.recharge.get(kper)
				if arr is None:
					arr = 0.0
				spd[kper] = self._as_recharge_flat(arr, kper=kper)
			return spd

		if isinstance(self.recharge, Real) and not isinstance(self.recharge, bool):
			scalar = float(self.recharge)
			for kper in range(self.nper):
				spd[kper] = self._scalar_to_flat(scalar)
			return spd

		for kper in range(self.nper):
			scalar = self._series_like_to_scalar(kper)
			spd[kper] = self._scalar_to_flat(scalar)
		return spd

	def _empty_recharge_aux(self) -> dict[int, list[np.ndarray]]:
		return {
			k: [np.zeros(int(self.ncpl), dtype=float)]
			for k in range(int(self.nper))
		}

	def pre_processing(self, flow: object, domain: object, options: ModflowPreprocessOptions | None = None):
		self.flow = flow
		self.domain = domain
		active_options = self.preprocess_options if options is None else options
		self._apply_preprocess_options(active_options)
		self._validate_pre_processing_inputs()
		self._bind_recharge_from_flow()

		self.flow_regime = self._resolve_flow_regime() or "transient"
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

		self.grid_ctx = build_spatial_discretization(
			domain=self.domain,
			sgrid_config=getattr(self.modflow_config, "sgrid", None),
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
			required_properties=resolve_required_flow_properties(flow_regime=self.flow_regime),
			optional_fill_values={"Sy": 0.0, "Ss": 0.0},
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

		self.npf = flopy.mf6.ModflowGwfnpf(
			self.gwf,
			icelltype=np.ones((self.nlay,), dtype=int),
			k=self.hk,
			k33=self.hk / max(float(getattr(getattr(self.modflow_config, "process_specific", object()), "vka", 1.0)), 1e-12),
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

		drainage_cond_series = self._resolve_drainage_conductance_series()
		if drainage_cond_series is not None:
			drn_spd = {}
			top_flat = solver_mesh.top  # (ncpl,)
			dem_mask_flat = np.asarray(self.dem_mask, dtype=bool).reshape(-1)
			ocean_mask_flat = np.asarray(ocean_support_mask, dtype=bool).reshape(-1)
			cell_areas = solver_mesh.cell_areas()  # per-cell areas
			for kper in range(int(self.nper)):
				period_cells = []
				configured_cond_value = float(drainage_cond_series[kper])
				for cid in range(int(self.ncpl)):
					if dem_mask_flat[cid] or ocean_mask_flat[cid]:
						continue
					if configured_cond_value > 0.0:
						cond_value = max(configured_cond_value, 1e-12)
					else:
						cond_value = max(float(self.hk[0, cid]) * float(cell_areas[cid]), 1e-12)
					period_cells.append([0, cid, float(top_flat[cid]), cond_value])
				drn_spd[kper] = period_cells
			self.drn = flopy.mf6.ModflowGwfdrn(self.gwf, stress_period_data=drn_spd, save_flows=True)

		side_chd_spd = self._build_side_boundary_chd_spd()
		chd_spd = {}
		for kper in range(int(self.nper)):
			period_map: dict[tuple[int, int], list[float]] = {}
			for entry in ocean_chd_spd.get(kper, []):
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

	def processing(self, options: ModflowRunOptions | None = None):
		if options is None:
			options = ModflowRunOptions()
		elif not isinstance(options, ModflowRunOptions):
			raise TypeError("processing options must be ModflowRunOptions")

		if options.write_model:
			self.sim.write_simulation(silent=not options.verbose)

		success_model = False
		if options.run_model:
			success_model, _ = self.sim.run_simulation(silent=not options.verbose)
		return success_model

	@staticmethod
	def _get_budget_records_or_none(cbb: object, *, kstpkper: tuple[int, int], text: str):
		"""Return one budget term, or None when the term is absent from the file."""
		try:
			return cbb.get_data(kstpkper=kstpkper, text=text)
		except Exception as exc:
			message = str(exc)
			if "text string is not in the budget file" in message.lower():
				return None
			raise

	def post_processing(self, options: ModflowPostprocessOptions | None = None):
		if options is None:
			options = ModflowPostprocessOptions()
		elif not isinstance(options, ModflowPostprocessOptions):
			raise TypeError("post_processing options must be ModflowPostprocessOptions")

		self.save_file = os.path.join(self.full_path, "_postprocess")
		toolbox.create_folder(self.save_file)
		self.tifs_file = os.path.join(self.save_file, "_rasters")
		toolbox.create_folder(self.tifs_file)

		head_path = os.path.join(self.full_path, f"{self.model_name}.hds")
		cbc_path = os.path.join(self.full_path, f"{self.model_name}.cbc")
		head_fpu = bf.HeadFile(head_path)
		cbb = bf.CellBudgetFile(cbc_path)

		times = head_fpu.get_times()
		self.times = times
		dict_watertable_elevation = {}
		dict_watertable_depth = {}
		dict_seepage_areas = {}
		dict_outflow_drain = {}
		dict_accumulation_flux = {}

		ncpl = int(self.ncpl)
		dem_mask_flat = np.asarray(self.dem_mask, dtype=bool).reshape(-1)
		dem_flat = np.asarray(self.dem, dtype=float).reshape(-1)

		for item, time in enumerate(times):
			head = head_fpu.get_data(totim=time)
			wt = pp.get_water_table(head, -9999)
			wt = np.asarray(wt, dtype=float).reshape(-1)  # flatten to (ncpl,)
			wt[np.isnan(wt)] = -9999
			wt[wt <= -1e20] = -9999

			if options.watertable_elevation:
				wt_out = wt.copy()
				wt_out[dem_mask_flat] = -9999
				dict_watertable_elevation[item] = self._to_export_array(wt_out)
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, self._to_export_array(wt_out), os.path.join(self.tifs_file, f"watertable_elevation_t({item}).tif"), -9999)

			if options.watertable_depth:
				wtd = np.where(dem_mask_flat, -9999, np.maximum(dem_flat - wt, 0))
				dict_watertable_depth[item] = self._to_export_array(wtd)
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, self._to_export_array(wtd), os.path.join(self.tifs_file, f"watertable_depth_t({item}).tif"), -9999)

			drn = self._get_budget_records_or_none(
				cbb,
				kstpkper=(0, item),
				text="DRN",
			)
			outflow = np.zeros(ncpl, dtype=float)
			seepage = np.zeros(ncpl, dtype=float)
			if drn is not None and len(drn) > 0:
				rec = drn[0]
				try:
					if getattr(rec, "dtype", None) is not None and rec.dtype.names is not None:
						node_field = "node" if "node" in rec.dtype.names else rec.dtype.names[0]
						q_field = "q" if "q" in rec.dtype.names else rec.dtype.names[-1]
						iterator = ((int(r[node_field]), float(r[q_field])) for r in rec)
					else:
						iterator = ((int(r[0]), float(r[-1])) for r in rec)
					for node, q in iterator:
						if node <= 0:
							continue
						# DISV node numbering: node = layer * ncpl + cell_id + 1
						layer = (node - 1) // ncpl
						cell_id = (node - 1) % ncpl
						if layer == 0:
							outflow[cell_id] += max(-q, 0.0)
							seepage[cell_id] = 1.0 if q < 0 else seepage[cell_id]
				except Exception:
					pass

			outflow[dem_mask_flat] = -9999
			seepage[dem_mask_flat] = -9999

			outflow_tif_path = os.path.join(self.tifs_file, f"outflow_drain_t({item}).tif")
			if options.outflow_drain:
				dict_outflow_drain[item] = self._to_export_array(outflow)
			if options.outflow_drain or options.accumulation_flux:
				if options.accumulation_flux or options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, self._to_export_array(outflow), outflow_tif_path, -9999)
			if options.seepage_areas:
				dict_seepage_areas[item] = self._to_export_array(seepage)
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, self._to_export_array(seepage), os.path.join(self.tifs_file, f"seepage_areas_t({item}).tif"), -9999)

			if options.accumulation_flux and self.solver_mesh.is_structured:
				routing_ctx = self._ensure_solver_routing_context()
				accumulated_flow = masstransfer.Masstransfer(
					self.geographic,
					f"outflow_drain_t({item}).tif",
					f"tracept_t({item}).shp",
					f"accumulation_flux_t({item}).tif",
					extraction_folder=self.save_file,
					routing_fill_path=routing_ctx.correc_path,
					routing_direc_path=routing_ctx.direc_path,
				)
				accumulated_flow.trace_cumulated()
				with rasterio.open(os.path.join(self.tifs_file, f"accumulation_flux_t({item}).tif")) as src:
					dict_accumulation_flux[item] = src.read(1)

		if options.watertable_elevation:
			np.save(os.path.join(self.save_file, "watertable_elevation"), dict_watertable_elevation)
		if options.watertable_depth:
			np.save(os.path.join(self.save_file, "watertable_depth"), dict_watertable_depth)
		if options.seepage_areas:
			np.save(os.path.join(self.save_file, "seepage_areas"), dict_seepage_areas)
		if options.outflow_drain:
			np.save(os.path.join(self.save_file, "outflow_drain"), dict_outflow_drain)
		if options.accumulation_flux:
			np.save(os.path.join(self.save_file, "accumulation_flux"), dict_accumulation_flux)


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

	def post_processing(
		self,
		model_mt3dms: object,
		concentration_seepage: bool = True,
		mass_seepage: bool = True,
		mass_accumulated: bool = False,
		export_all_tif: bool = False,
	):
		self.save_file = os.path.join(self.full_path, "_postprocess")
		toolbox.create_folder(self.save_file)
		self.tifs_file = os.path.join(self.save_file, "_rasters")
		toolbox.create_folder(self.tifs_file)

		path_ucn = os.path.join(self.full_path, f"{self.model_name_mt}.ucn")
		try:
			ucnobj = bf.UcnFile(path_ucn)
			concobj_1c = ucnobj.get_alldata(mflay=None)
		except Exception:
			# MF6-GWT concentration output may use HeadFile structure with double precision.
			try:
				headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="double")
				concobj_1c = headobj.get_alldata(mflay=None)
			except Exception:
				headobj = bf.HeadFile(path_ucn, text="CONCENTRATION", precision="single")
				concobj_1c = headobj.get_alldata(mflay=None)
		concobj_1c[concobj_1c >= 1e30] = np.nan
		conc_last_idx = max(int(concobj_1c.shape[0]) - 1, 0)

		outflow_drain = np.load(os.path.join(self.save_file, "outflow_drain.npy"), allow_pickle=True).item()
		dem_mask = np.asarray(
			getattr(self.model_modflow, "dem_mask", self.model_modflow.dem < -9999),
			dtype=bool,
		).reshape(-1)

		dict_concentration_seepage = {}
		dict_mass_seepage = {}
		dict_mass_accumulated = {}

		def _reshape_for_export(arr):
			return self.model_modflow._to_export_array(np.asarray(arr, dtype=float).reshape(-1))

		for i in range(self.model_modflow.nper):
			the_time = str(i + 1)
			seep = outflow_drain.get(i, np.zeros(int(self.model_modflow.ncpl), dtype=float))
			seep = np.asarray(seep, dtype=float).reshape(-1)
			conc_time_idx = min(i, conc_last_idx)

			if concentration_seepage:
				conc_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
				conc_surf[seep <= 0] = -9999
				conc_surf[dem_mask] = -9999
				dict_concentration_seepage[i] = _reshape_for_export(conc_surf)
				if export_all_tif or i == 0:
					toolbox.export_tif(self.model_modflow.dem_watershed_path, _reshape_for_export(conc_surf), os.path.join(self.tifs_file, f"concentration_seepage_t({the_time}).tif"), -9999)

			if mass_seepage:
				mass_surf = np.asarray(concobj_1c[conc_time_idx][0], dtype=float).reshape(-1).copy()
				mass_surf[seep <= 0] = np.nan
				mass_surf = mass_surf * seep
				mass_surf[dem_mask] = -9999
				mass_surf = np.where(np.isnan(mass_surf), -9999, mass_surf)
				dict_mass_seepage[i] = _reshape_for_export(mass_surf)
				if export_all_tif or i == 0:
					toolbox.export_tif(self.model_modflow.dem_watershed_path, _reshape_for_export(mass_surf), os.path.join(self.tifs_file, f"mass_seepage_t({the_time}).tif"), -9999)

			if mass_accumulated:
				routing_ctx = self.model_modflow._ensure_solver_routing_context()
				accumulated_mass = masstransfer.Masstransfer(
					self.model_modflow.geographic,
					f"mass_seepage_t({the_time}).tif",
					f"tracept_conc_t({the_time}).shp",
					f"mass_accumulated_t({the_time}).tif",
					extraction_folder=self.save_file,
					routing_fill_path=routing_ctx.correc_path,
					routing_direc_path=routing_ctx.direc_path,
				)
				accumulated_mass.trace_cumulated()
				with bf.HeadFile(os.path.join(self.tifs_file, f"mass_accumulated_t({the_time}).tif")) as src:
					dict_mass_accumulated[i] = src.read(1)

		if concentration_seepage:
			np.save(os.path.join(self.save_file, "concentration_seepage"), dict_concentration_seepage)
		if mass_seepage:
			np.save(os.path.join(self.save_file, "mass_seepage"), dict_mass_seepage)
		if mass_accumulated:
			np.save(os.path.join(self.save_file, "mass_accumulated"), dict_mass_accumulated)

