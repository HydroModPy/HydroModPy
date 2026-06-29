# Lake bed reconstruction from bathymetry (abacus-reconciled carving)

Status: implemented (2026-06-26). Opt-in per lake via
`flow.sinks_sources.lakes.<id>.bed_reconstruction`.

## Problem

Before this feature a HydroModPy lake was a flat-bottomed reservoir: the lake
footprint cells were deactivated over `occupied_layers` whole grid layers, the
LAK exchange elevations came from the grid layer surfaces, and the
`lake_bathymetry` raster was loaded but consumed by nothing. The abacus carried
the storage (stage-volume-area) but the *bed geometry* the groundwater saw was a
layer-quantized prism, so the flow lines around the lake did not follow the real
basin.

## What it does

When a lake sets `bed_reconstruction`, the MF6 build carves the real bed:

1. **Regrid** the `lake_bathymetry` raster onto the lake cells by zonal mean
   (`spatial/lake_bed/regrid.py`) - conservative, volume-aware, unlike a single
   centroid bilinear sample. Bilinear fallback where a cell holds too few pixels.
2. **Reconcile** the regridded bed to the abacus by *area-weighted quantile
   mapping* (`spatial/lake_bed/reconcile.py`). The abacus `sarea(stage)` is the
   wetted-area-below-elevation curve; the remap keeps the bathymetric spatial
   rank order (deep stays deep) but re-assigns elevations so the cell
   area-vs-elevation distribution matches the abacus. Exact, one pass. Matching
   the area-stage curve matches volume by integration. The mesh footprint vs
   abacus full-pool area ratio is reported as `area_scale` and absorbed first.
3. **Carve** each lake column (`spatial/lake_bed/carve_math.py` +
   `solver/modflow6/builders/lake.py:carve_lake_bed`): the bottom of the deepest
   occupied layer is set to the bed, the inactive cap `[bed, top]` and the active
   aquifer `[base, bed]` are each re-proportioned, with a `min_thickness` clamp
   so the column stays a strict-monotone valid prism and the aquifer base is
   fixed. The first active cell below therefore exchanges with the lake at the
   real bed elevation.

`carve_lake_bed` runs in `build.py` just before `apply_lake_idomain_mask`, so the
carved `top`/`botm` flow into DISV, the start heads and the LAK connectiondata.

## Why quantile mapping, not iteration

A 1-D hypsometric curve does not determine a 2-D bed field (many beds share one
curve). Iterating a DEM until the simulated and reference abacus curves converge
is ill-posed, non-unique and slow. The area-weighted quantile map is the exact,
deterministic, one-pass solution: bathymetry gives the spatial pattern, the
abacus gives the correct integral. The degenerate prismatic abacus (constant
`sarea`) carves a flat bottom, as it should.

## Two surfaces, never one

The carving touches only the MF6 model `top`/`botm`. The catchment-delineation /
routing DEM (already depression-breached) is a separate product and is untouched,
so "no internal sink, single outlet" stays a routing-DEM property while the model
top carries the real basin. MODFLOW does no surface D8 routing on `top`.

## Diagnostic figure

`display/figures/lake_abacus_comparison.py` plots the reference abacus vs the
abacus the carved grid actually represents (stage-volume and stage-area), with
storage NSE/RMSE. The simulated abacus is pre-computed in the solver layer and
stashed on `model._lake_bed_reconstruction` so the display figure only receives
arrays. `reporting/lake_abacus_report.py:plot_lake_abacus_comparison_for_model`
renders one PNG per reconstructed lake from a built model.

## Active-littoral (marnage) mode

`bed_reconstruction.dynamic_area = true` switches from the fixed-area
inactive-footprint reservoir to the MF6-native **drying-and-rewetting** lake
(TM 6-A55 "Drying and Rewetting of Sections of a Lake"; lak.tex "Use of the Lake
Package with RCH and EVT"). Instead of deactivating the footprint:

- the lakebed cells stay **ACTIVE**, with their carved bathymetric bed as the
  cell **top** (`regrade_column_active_top`),
- each gets **one VERTICAL** LAK connection on the cell itself
  (`build_lake_connectiondata(dynamic_area=True)`),
- RCH/EVT are **applied** over them (excluded from the lake mask in `build.py`).

MF6 then toggles each cell per timestep in `lak_cf` (gwf-lak.f90:3536-3542):
`if hlak > belev (= cell top = bed) -> ibound=IWETLAKE` (RCH/ET zeroed, lake
exchange computed) `else ibound=1` (recharges as land, lake connection dry,
wetted area drops by that cell's area). This is exact per-cell marnage: the
shoreline retreat band reverts to recharged land, with no double counting. A
small `surfdep` (0.1, default) smooths the switch for Newton.

Verified by a real MF6 solve (`tests/integration/test_modflow6_lake_marnage.py`):
a graded bed with a CONSTANT-stage lake high then low shows areal recharge
exactly zero while submerged and exactly `n_emerged * rate * cell_area` once the
higher-bed cells emerge. TOLERANCES row 50.

The fixed-area mode (`dynamic_area = false`, default) keeps the classic
inactive-footprint carve and is unchanged.

## Config

```toml
[data.lake_bathymetry]
[[data.lake_bathymetry.sources]]
source = "custom"
path = "data/lake_bathymetry/lake_bathymetry_custom_lac0.tif"

[flow.sinks_sources.lakes.lac0.bed_reconstruction]
reconcile_to_abacus = true   # abacus is the storage source of truth
min_thickness = 0.5          # [L] keeps columns valid prisms
min_pixels = 1               # zonal-mean pixel threshold
dynamic_area = true          # active-littoral marnage (RCH/ET toggled per cell)
```

## Tests

- `tests/unit/spatial/test_lake_bed_reconstruction.py` - regrid, reconcile
  (NSE > 0.999), flat-bottom degenerate case, column re-grading, simulate.
- `tests/unit/solver/test_modflow6_lake_bed_carve.py` - full carve on a real
  SolverMesh + real GeoTIFF, basin shape (centre deeper than rim), abacus match,
  and flopy DISV ingestion of the carved geometry (strict bot < top).
- `tests/unit/display/test_lake_abacus_comparison.py` - figure + report helper.
- TOLERANCES.md row 49.

## Per-cell occupied_layers (done)

For the fixed-area (inactive-footprint) carve, the number of deactivated cap
layers is now **per cell**: `carve_lake_bed` derives `occ_c = count(botm_pre >
bed)` per cell (deep centre cuts more layers than a shallow rim), clamps to
`[1, nlay-1]`, pins the bed at `botm[occ_c-1]`, and stashes
`model._lake_occupied_layers_by_cell`. `apply_lake_idomain_mask` and
`build_lake_connectiondata` both take an optional `occupied_layers_by_cell` and
clip the bank-seepage extent per column. Lakes without bathymetry fall back to
the scalar `occupied_layers`, unchanged.

## Abacus figure auto-render via `[display].figures` (done)

The comparison is now a registered `BaseFigure` (`lake_abacus_comparison`). The
build writes a `{stem}.lake_abacus.json` sidecar; the flow extractor lands it into
the per-sim Zarr group `lake_abacus/<lake_id>` (`zarr_writer`/`zarr_reader` +
`SimulationZarr` + catalog store); the figure reads it via the module-level
`results.lake_abacus_view.run_lake_abacus` (kept off the `Run` surface to respect
the 50-method cap). List `lake_abacus_comparison` in `[display].figures` and it
auto-renders after a run. No DB migration (Zarr only).

## Exposed-band runoff via the MODFLOW 6 BMI API (mechanism done, auto-wiring deferred)

The recharge on the exposed marnage band is already handled (RCH toggled per
cell). The *runoff* of the dry band needs the simulated stage per timestep, which
is unknown at build time. Mass-balance check: the water is NOT lost today, the
catchment runoff covers the full footprint area (lumped) and reaches the lake;
what is missing is the dynamic per-band attribution.

The dynamic coupling is implemented through the existing libmf6 BMI runner
(`mf6_runner="api"`): `Mf6ApiContext.lak_get/lak_set` (raw `get_var_address` path,
which works at `timestep_start` where the modflowapi AdvancedPackage wrapper
raises) + `read_lake_runoff`/`write_lake_runoff`; `lake_band_runoff.py` holds the
pure `exposed_band_area` / `LakeBandRunoffSpec.runoff_at` and the
`make_exposed_band_runoff_callback` factory. At each `timestep_start` it reads
`XNEWPAK`, sizes the band, and sets LAK `RUNOFF = base + rate * exposed_area`.
Proven by a real BMI solve (`tests/integration/test_lake_band_runoff_api.py`):
zero runoff at full pool, `rate * exposed_area` once cells emerge. Config flag
`bed_reconstruction.exposed_band_runoff`.

Auto-activation in `hmp run` is now wired end to end:
- the binder surfaces the watershed runoff RATE [m/s] onto the lake payload, but
  only for lakes with `exposed_band_runoff` (binder behaviour unchanged otherwise);
- the LAK build assembles `LakeBandRunoffSpec` per such lake (`lake_index` == LAK
  ifno; rate from the surfaced forcing; base from the lake's own runoff volume,
  which is empty when SFR routes it, so no double counting) and stashes them on
  `model._exposed_band_runoff_specs`;
- `_resolve_modflow_runner` returns `"api"` whenever those specs exist (forces the
  in-process runner for that model only);
- `_run_via_api` builds and attaches the callback from the specs.
A config validator rejects `exposed_band_runoff` without `dynamic_area`. Tests:
`tests/unit/solver/test_lake_band_runoff_wiring.py` (specs + runner force +
validator) on top of the real BMI proof.

For an SFR-routed marnage reservoir (the target case) the lake has no direct
runoff volume, so the band term `rate * exposed_area` is the only lake runoff:
clean, no double counting. For a no-SFR lake the lumped runoff already covers the
footprint, so the band term would slightly double-count there (documented edge).

## Deferred

- **No-SFR double-count refinement**: subtract the footprint area from the lumped
  catchment runoff when a no-SFR marnage lake uses `exposed_band_runoff`.
- **Process-parallel BMI** for calibration (the api runner is serial-only).
- **Spatially-variable `bedleak`**: geometry first; leakance stays per-lake.
