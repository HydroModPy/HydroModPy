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
from flopy.utils import postprocessing as pp

from hydromodpy.domain.surface import Surface
from hydromodpy.modeling import masstransfer
from hydromodpy.solver import Solver
from hydromodpy.solver.modflow_nwt.modflow import (
	ModflowPostprocessOptions,
	ModflowPreprocessOptions,
	ModflowRunOptions,
)
from hydromodpy.solver.modflow6.modflow6_config import (
	Modflow6Config,
	_coerce_modflow6_config,
)
from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
	resolve_flow_property_arrays,
)
from hydromodpy.solver.transport_common.runtime_arrays import (
	build_concentration_runtime_overrides,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.solver.utils.temporal.tmesh_generation import TMesh_Generation
from hydromodpy.tools import get_logger, toolbox

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
			dem_source = self.geographic.dem_box_buff_data
			self.dem_watershed_path = self.geographic.watershed_box_buff_dem
		else:
			dem_source = self.geographic.dem_data
			self.dem_watershed_path = self.geographic.watershed_buff_dem

		self.box = bool(box)
		dem = np.asarray(dem_source, dtype=float).copy()
		dem[(dem <= -9999) | (dem >= 9999)] = -9999
		self.dem = dem
		self.nrow = int(dem.shape[0])
		self.ncol = int(dem.shape[1])

	def _apply_preprocess_options(self, options: ModflowPreprocessOptions | None = None) -> None:
		if options is None:
			options = self.preprocess_options
		if not isinstance(options, ModflowPreprocessOptions):
			raise TypeError("pre_processing options must be a ModflowPreprocessOptions instance.")

		self.preprocess_options = options
		self.sink_fill = bool(options.sink_fill)
		self.recharge = getattr(options, "recharge", None)
		self.first_clim = getattr(options, "first_clim", None)
		self.check_grid = bool(options.check_grid)
		self._select_active_dem(box=bool(options.box))

	def _get_domain_surfaces(self):
		if self.domain is None:
			raise ValueError("Modflow6 spatial geometry is domain-only: a Domain object is required.")

		surface_topo = getattr(self.domain, "surface_topo", None)
		substratum = getattr(self.domain, "substratum", None)
		if surface_topo is None or substratum is None:
			raise ValueError("domain.surface_topo and domain.substratum are required.")
		if not isinstance(surface_topo, Surface) or not isinstance(substratum, Surface):
			raise TypeError("Domain surfaces must be Surface instances.")

		top = np.asarray(surface_topo.as_array(), dtype=float)
		bot = np.asarray(substratum.as_array(), dtype=float)
		if top.shape != bot.shape:
			raise ValueError(f"Domain surface mismatch: top{top.shape} != substratum{bot.shape}.")
		if top.shape != self.dem.shape:
			raise ValueError("Domain surface shape must match active DEM support.")

		surface_topo.assert_same_geographic_domain(substratum)
		return surface_topo, substratum

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

	def _build_well_stress_period_data(self, n_stress_periods: int) -> dict[int, list[list[float]]]:
		if n_stress_periods <= 0 or self.flow is None:
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

		normalized_wells: list[tuple[tuple[int, int, int], np.ndarray]] = []
		for _, raw_well_payload in wells.items():
			cell_payload = getattr(raw_well_payload, "cell", None)
			flux_payload = getattr(raw_well_payload, "flux", None)
			if cell_payload is None and isinstance(raw_well_payload, Mapping):
				cell_payload = raw_well_payload.get("cell")
				flux_payload = raw_well_payload.get("flux")
			if cell_payload is None or flux_payload is None:
				continue

			cell_seq = list(cell_payload)
			if len(cell_seq) != 3:
				continue
			cell = (int(cell_seq[0]), int(cell_seq[1]), int(cell_seq[2]))

			if isinstance(flux_payload, Real) and not isinstance(flux_payload, bool):
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
			spd[t] = [[cell[0], cell[1], cell[2], float(flux_vector[t])] for cell, flux_vector in normalized_wells]
		return spd

	def _scalar_to_2d(self, value: float) -> np.ndarray:
		return np.full((self.nrow, self.ncol), float(value), dtype=float)

	def _as_recharge_2d(self, value: object, *, kper: int | None = None) -> np.ndarray:
		if isinstance(value, Real) and not isinstance(value, bool):
			return self._scalar_to_2d(float(value))

		arr = np.asarray(value, dtype=float)
		if arr.ndim == 0:
			return self._scalar_to_2d(float(arr))
		if arr.ndim == 1:
			if arr.size == 0:
				return np.zeros((self.nrow, self.ncol), dtype=float)
			if kper is None:
				return self._scalar_to_2d(float(arr[-1]))
			idx = min(max(int(kper), 0), int(arr.size) - 1)
			return self._scalar_to_2d(float(arr[idx]))
		if arr.ndim == 2:
			if arr.shape == (self.nrow, self.ncol):
				return arr.astype(float)
			raised = arr.ravel()
			if raised.size == 0:
				return np.zeros((self.nrow, self.ncol), dtype=float)
			return self._scalar_to_2d(float(raised[-1]))
		if arr.ndim >= 3:
			if kper is None:
				kper = 0
			idx = min(max(int(kper), 0), int(arr.shape[0]) - 1)
			slice_2d = np.asarray(arr[idx], dtype=float)
			if slice_2d.shape == (self.nrow, self.ncol):
				return slice_2d
			flat = slice_2d.ravel()
			if flat.size == 0:
				return np.zeros((self.nrow, self.ncol), dtype=float)
			return self._scalar_to_2d(float(flat[-1]))

		return np.zeros((self.nrow, self.ncol), dtype=float)

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
				spd[kper] = self._as_recharge_2d(arr, kper=kper)
			return spd

		if isinstance(self.recharge, Real) and not isinstance(self.recharge, bool):
			scalar = float(self.recharge)
			for kper in range(self.nper):
				spd[kper] = self._scalar_to_2d(scalar)
			return spd

		for kper in range(self.nper):
			scalar = self._series_like_to_scalar(kper)
			spd[kper] = self._scalar_to_2d(scalar)
		return spd

	def _empty_recharge_aux(self) -> dict[int, list[np.ndarray]]:
		return {
			k: [np.zeros((self.nrow, self.ncol), dtype=float)]
			for k in range(int(self.nper))
		}

	def pre_processing(self, flow: object, domain: object, options: ModflowPreprocessOptions | None = None):
		self.flow = flow
		self.domain = domain
		active_options = self.preprocess_options if options is None else options
		self._apply_preprocess_options(active_options)

		self.flow_regime = self._resolve_flow_regime() or "transient"

		builder_kwargs = self.modflow_config.tgrid.to_builder_kwargs() if getattr(self.modflow_config, "tgrid", None) else {}
		builder_kwargs["flow_regime"] = self.flow_regime
		tgrid = TMesh_Generation(**builder_kwargs).run() if builder_kwargs else None

		if tgrid is not None:
			self.nper = int(np.asarray(getattr(tgrid, "perlen", []), dtype=float).size)
			self.perlen = np.asarray(getattr(tgrid, "perlen", []), dtype=float)
			self.nstp = np.asarray(getattr(tgrid, "nstp", []), dtype=int)
			self.steady = np.asarray(getattr(tgrid, "steady_state", []), dtype=bool)
		else:
			self.nper = 1
			self.perlen = np.asarray([1.0], dtype=float)
			self.nstp = np.asarray([1], dtype=int)
			self.steady = np.asarray([self.flow_regime == "steady"], dtype=bool)

		surface_topo, bottom_surface = self._get_domain_surfaces()
		sgrid = StructuredGridBuilder().build_from_surfaces(
			top_surface=surface_topo,
			bottom_surface=bottom_surface,
			vertical_config=getattr(self.modflow_config, "sgrid", None),
		)
		self.nlay = int(sgrid.nlay)
		self.nrow = int(sgrid.nrow)
		self.ncol = int(sgrid.ncol)

		flow_params = resolve_flow_property_arrays(
			flow=self.flow,
			domain=self.domain,
			sgrid=sgrid,
		)
		self.hk = flow_params["hk"]
		self.sy = flow_params["sy"]
		self.ss = flow_params["ss"]

		runtime = getattr(self.modflow_config, "runtime", None)
		sim_name = self.model_name_mf6
		self.sim = flopy.mf6.MFSimulation(sim_name=sim_name, sim_ws=self.full_path, exe_name=self.exe)
		self.tdis = flopy.mf6.ModflowTdis(
			self.sim,
			nper=int(self.nper),
			perioddata=[(float(self.perlen[i]), int(self.nstp[i]), 1.0) for i in range(int(self.nper))],
			time_units=getattr(getattr(self.modflow_config, "tgrid", None), "itmuni", "days"),
		)
		self.ims = flopy.mf6.ModflowIms(
			self.sim,
			print_option="SUMMARY" if getattr(runtime, "mf_verbose", False) else "NONE",
			complexity=getattr(runtime, "mf6_ims_complexity", "COMPLEX"),
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

		self.dis = flopy.mf6.ModflowGwfdis(
			self.gwf,
			nlay=self.nlay,
			nrow=self.nrow,
			ncol=self.ncol,
			delr=np.asarray(sgrid.delr, dtype=float),
			delc=np.asarray(sgrid.delc, dtype=float),
			top=np.asarray(sgrid.top, dtype=float),
			botm=np.asarray(sgrid.botm, dtype=float),
			xorigin=float(sgrid.xoffset),
			yorigin=float(sgrid.yoffset),
			length_units="METERS",
		)

		h_ic = self.flow.initial_conditions.get("h")
		if h_ic is None:
			raise ValueError("flow.ic.h is required for Modflow6 pre_processing")
		if h_ic.type == "top":
			strt = np.repeat(np.asarray(sgrid.top, dtype=float)[np.newaxis, :, :], self.nlay, axis=0)
		elif h_ic.type == "bot":
			bottom = np.asarray(sgrid.botm, dtype=float)
			strt = np.repeat(bottom[-1][np.newaxis, :, :], self.nlay, axis=0)
		else:
			strt = np.full((self.nlay, self.nrow, self.ncol), float(h_ic.value), dtype=float)
		self.ic = flopy.mf6.ModflowGwfic(self.gwf, strt=strt)

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

		if "drainage" in self.flow.boundary_conditions:
			drn_spd = {}
			for kper in range(int(self.nper)):
				period_cells = []
				top = np.asarray(sgrid.top, dtype=float)
				cond = np.maximum(self.hk[0] * (np.asarray(sgrid.delr)[None, :] * np.asarray(sgrid.delc)[:, None]) / np.maximum(self.resolution, 1e-6), 1e-12)
				for i in range(self.nrow):
					for j in range(self.ncol):
						if top[i, j] <= -9999:
							continue
						period_cells.append([0, i, j, float(top[i, j]), float(cond[i, j])])
				drn_spd[kper] = period_cells
			self.drn = flopy.mf6.ModflowGwfdrn(self.gwf, stress_period_data=drn_spd, save_flows=True)

		chd_spd = {}
		bc = self.flow.boundary_conditions
		for kper in range(int(self.nper)):
			entries = []
			if "west_boundary" in bc:
				val = float(getattr(bc["west_boundary"], "value", 0.0))
				for i in range(self.nrow):
					entries.append([0, i, 0, val])
			if "east_boundary" in bc:
				val = float(getattr(bc["east_boundary"], "value", 0.0))
				for i in range(self.nrow):
					entries.append([0, i, self.ncol - 1, val])
			if "north_boundary" in bc:
				val = float(getattr(bc["north_boundary"], "value", 0.0))
				for j in range(self.ncol):
					entries.append([0, 0, j, val])
			if "south_boundary" in bc:
				val = float(getattr(bc["south_boundary"], "value", 0.0))
				for j in range(self.ncol):
					entries.append([0, self.nrow - 1, j, val])
			chd_spd[kper] = entries
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

		for item, time in enumerate(times):
			head = head_fpu.get_data(totim=time)
			wt = pp.get_water_table(head, -9999)
			wt[np.isnan(wt)] = -9999
			if options.watertable_elevation:
				dict_watertable_elevation[item] = wt
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, wt, os.path.join(self.tifs_file, f"watertable_elevation_t({item}).tif"), -9999)

			if options.watertable_depth:
				wtd = np.where(self.dem <= -9999, -9999, np.maximum(self.dem - wt, 0))
				dict_watertable_depth[item] = wtd
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, wtd, os.path.join(self.tifs_file, f"watertable_depth_t({item}).tif"), -9999)

			drn = cbb.get_data(kstpkper=(item, item), text="DRN")
			outflow = np.zeros((self.nrow, self.ncol), dtype=float)
			seepage = np.zeros((self.nrow, self.ncol), dtype=float)
			if drn is not None and len(drn) > 0:
				rec = drn[0]
				try:
					for r in rec:
						node = int(r[0]) if len(r) > 1 else 0
						q = float(r[1]) if len(r) > 1 else 0.0
						if node <= 0:
							continue
						layer = (node - 1) // (self.nrow * self.ncol)
						rem = (node - 1) % (self.nrow * self.ncol)
						i = rem // self.ncol
						j = rem % self.ncol
						if layer == 0:
							outflow[i, j] += max(-q, 0.0)
							seepage[i, j] = 1.0 if q < 0 else seepage[i, j]
				except Exception:
					pass

			outflow[self.dem <= -9999] = -9999
			seepage[self.dem <= -9999] = -9999

			if options.outflow_drain:
				dict_outflow_drain[item] = outflow
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, outflow, os.path.join(self.tifs_file, f"outflow_drain_t({item}).tif"), -9999)
			if options.seepage_areas:
				dict_seepage_areas[item] = seepage
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, seepage, os.path.join(self.tifs_file, f"seepage_areas_t({item}).tif"), -9999)

			if options.accumulation_flux:
				acc = np.where(outflow == -9999, -9999, outflow)
				dict_accumulation_flux[item] = acc
				if options.export_all_tif or item == 0:
					toolbox.export_tif(self.dem_watershed_path, acc, os.path.join(self.tifs_file, f"accumulation_flux_t({item}).tif"), -9999)

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
		nrow = int(self.model_modflow.nrow)
		ncol = int(self.model_modflow.ncol)
		if isinstance(self.sconc_input, dict):
			out = {}
			for k in range(nper):
				arr = self.sconc_input.get(k)
				if arr is None:
					arr = np.zeros((nrow, ncol), dtype=float)
				out[k] = np.asarray(arr, dtype=float)
			return out
		val = float(self.sconc_input)
		return {k: np.full((nrow, ncol), val, dtype=float) for k in range(nper)}

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
				replace=True,
			)

		dis = self.model_modflow.dis
		self.gwtdis = flopy.mf6.ModflowGwtdis(
			self.gwt,
			nlay=self.model_modflow.nlay,
			nrow=self.model_modflow.nrow,
			ncol=self.model_modflow.ncol,
			delr=np.asarray(dis.delr.array, dtype=float),
			delc=np.asarray(dis.delc.array, dtype=float),
			top=np.asarray(dis.top.array, dtype=float),
			botm=np.asarray(dis.botm.array, dtype=float),
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
			headobj = bf.HeadFile(path_ucn, text="CONCENTRATION")
			concobj_1c = headobj.get_alldata(mflay=None)
		concobj_1c[concobj_1c >= 1e30] = np.nan
		conc_last_idx = max(int(concobj_1c.shape[0]) - 1, 0)

		outflow_drain = np.load(os.path.join(self.save_file, "outflow_drain.npy"), allow_pickle=True).item()
		dem_mask = self.model_modflow.dem < -9999

		dict_concentration_seepage = {}
		dict_mass_seepage = {}
		dict_mass_accumulated = {}

		for i in range(self.model_modflow.nper):
			the_time = str(i + 1)
			seep = outflow_drain.get(i, np.zeros((self.model_modflow.nrow, self.model_modflow.ncol), dtype=float))
			conc_time_idx = min(i + 1, conc_last_idx)

			if concentration_seepage:
				conc_surf = concobj_1c[conc_time_idx][0].copy()
				conc_surf[seep <= 0] = -9999
				conc_surf[dem_mask] = -9999
				dict_concentration_seepage[i] = conc_surf
				if export_all_tif or i == 0:
					toolbox.export_tif(self.model_modflow.dem_watershed_path, conc_surf, os.path.join(self.tifs_file, f"concentration_seepage_t({the_time}).tif"), -9999)

			if mass_seepage:
				mass_surf = concobj_1c[conc_time_idx][0].copy()
				mass_surf[seep <= 0] = np.nan
				mass_surf = mass_surf * seep
				mass_surf[dem_mask] = -9999
				mass_surf = np.where(np.isnan(mass_surf), -9999, mass_surf)
				dict_mass_seepage[i] = mass_surf
				if export_all_tif or i == 0:
					toolbox.export_tif(self.model_modflow.dem_watershed_path, mass_surf, os.path.join(self.tifs_file, f"mass_seepage_t({the_time}).tif"), -9999)

			if mass_accumulated:
				accumulated_mass = masstransfer.Masstransfer(
					self.model_modflow.geographic,
					f"mass_seepage_t({the_time}).tif",
					f"tracept_conc_t({the_time}).shp",
					f"mass_accumulated_t({the_time}).tif",
					extraction_folder=self.save_file,
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

