# Cheze downstream two-watershed routing + HFB voile depth - design & prototype

Status 2026-07-08: PROTOTYPE VERIFIED (lake sub-basin delineation + 3-zone separation
confirmed on Cheze, see figures/calibration_summary/downstream_zones_prototype.png).
Remaining: wire into HMP core (geographic delineation + solver DRN routing + downstream
SFR reach + spillway mover), the HFB exact-depth patch, unit tests, validation run.

## Verified prototype result

- Lake outlet = max-accumulation cell in a ring just downstream of the lake footprint
  (D8 acc is unreliable INSIDE the flat breached lake; extract_catchment_from_point's snap
  recovers the correct pour point). Lake sub-basin 29.9 km2, model watershed 30.3 km2,
  below-dam strip 0.39 km2 (contiguous, touches the model outlet). Zones are clean.

## HFB voile depth finding

- HFB is layer-quantized (whole top layer, no sub-layer partial) AND barrier_bottom =
  top[cell_a] - depth uses the CARVED cell top (bed_reconstruction). A 10 m voile in a
  17.5 m top layer lands in layer 0 only (~17.5 m barrier); a 10 m top layer pushes it
  into 2 layers (carved-top vs botm mismatch). Fix = code patch: reference depth from the
  uncarved surface (or an absolute foot elevation) + layer interface at the foot, OR a
  sub-layer partial-conductance HFB. Not config-only. flow_barrier.py:90-98.

## Full design (from parallel code investigation)

### seam group

**Current:** DRN routing is a two-zone (binary) split today, not three.

(1) How the mask is built and applied:
- build.py `_watershed_drainage_mask` (hydromodpy/solver/modflow6/build.py:187-218) reads ONE polygon, `geographic.watershed_shp` (the model/topographic watershed), and calls `watershed_drainage_cell_mask` (sfr.py:629-648), a prepared point-in-polygon test over `solver_mesh.cell_centroids()`. It returns a boolean (n_cells,) mask: True = centroid inside the model watershed, False = buffer. None when the polygon is missing (then everything routes).
- The mask is passed as `watershed_cell_mask=` at build.py:722 into `build_drainage_mover_records` (sfr.py:651-744).
- Target set (sfr.py:697-717): for every SFR network with `route_drainage`, it appends ALL reach cells `(cell2d, ifno)` (703-706); if the network has `outflow_to_lake`, it ALSO adds the lake footprint as proxies (709-717): for each lake cell it finds the nearest terminal-to-lake reach (713-716) and appends `(lake_cell2d, terminal_ifno)`. So the lake footprint is a target that resolves to a terminal reach, never a direct DRN->LAK.
- Per-cell routing (sfr.py:723-744): iterate every period-0 DRN row (single-period required, 688-693, so the boundary_index == MVR provider id). If `watershed_cell_mask[cell2d]` is False (buffer) -> `continue`, no MVR, the row stays a plain DRN that leaves the model (727-731). Otherwise route by nearest planar centroid among ALL targets (732-733) and emit one MVR record DRN->SFR with FACTOR 1.0 t 

**Seams:**
- `hydromodpy/solver/modflow6/build.py` 187-218 - _watershed_drainage_mask: builds the single boolean in/out-of-watershed mask from geographic.watershed_shp. Must become a 3-way zone classifier (needs a 2nd polygon = the lake sub-basin).
- `hydromodpy/solver/modflow6/build.py` 706-723 - SFR/DRN routing block: drops reach/marnage DRN rows, then calls build_drainage_mover_records with lake_cells_by_number (719-721) and watershed_cell_mask=_watershed_drainage_mask(...) (722). Call site to pass the new zone array; must include the below-dam network in sfr_networks.
- `hydromodpy/solver/modflow6/builders/sfr.py` 629-648 - watershed_drainage_cell_mask: generic prepared point-in-polygon over centroids. Reuse it a 2nd time for the lake sub-basin polygon inside the new zone classifier.
- `hydromodpy/solver/modflow6/builders/sfr.py` 651-744 - build_drainage_mover_records: target pool build (697-717), lake-footprint proxy (709-717), single-period DRN provider-id contract (688-693), per-cell routing loop + buffer skip (723-744, skip 727-731). This is where zone-gated target selection goes.
- `hydromodpy/solver/modflow6/builders/sfr.py` 810-826 - _terminal_reaches: defines the terminal-to-lake reach the lake proxy maps to; context for why below-dam cells currently reach the lake.
- `examples/projects/19_cheze_reservoir/project.toml` 49-66,220-270 - Config establishing Zone B exists but has no target: domain_extent=watershed (49), outlet downstream of dam (55-57), below-dam reach removed (64-66), spillway lakeout=0 EXT-OUTFLOW (220-224), sfr cheze route_drainage+outflow_to_lake=1 truncated at shoreline (255-270).
- `hydromodpy/spatial/geographic/subbasin.py` 132-168 - Subbasin.generate_subbasin: existing snap_pour_points + watershed delineation from an XY outlet. Candidate machinery to delineate the lake sub-basin polygon at the dam location (no such polygon is produced today).

**Change plan:**
1. PREREQUISITE (data/config) - lake sub-basin polygon: no lake/reservoir sub-basin polygon exists today (only watershed_shp). Delineate one at the dam/reservoir outlet using the existing Subbasin.generate_subbasin machinery (hydromodpy/spatial/geographic/subbasin.py:132-168), persist it as e.g. lake_subbasin_shp, and expose its path on the model alongside geographic.watershed_shp so build.py can read it. Add a config field for the dam-outlet coordinate (e.g. under flow.sinks_sources.lakes.<name> or geographic) to drive the delineation.
1. PREREQUISITE (data/config) - downstream reach for Zone B to target: today there is NO below-dam reach (removed per project.toml:64-66). Add one so Zone B has a receiver: either a standalone network [flow.sinks_sources.sfr.cheze_below_dam] delineated from the dam to the model outlet with route_drainage=true and NO outflow_to_lake (so it terminates EXT-OUTFLOW), or a downstream reach segment. Optionally redirect the LAK spillway (project.toml:220-224, lakeout=0) to this reach via a LAK->SFR mover so all below-dam surface water is coherent.
1. CODE - mask split: change build.py `_watershed_drainage_mask` (build.py:187-218) to return a 3-valued np.int8 zone array instead of a bool mask. Read both polygons and classify each centroid via two calls to watershed_drainage_cell_mask (sfr.py:629-648): inside lake sub-basin -> ZONE_LAKE; inside model watershed but outside lake sub-basin -> ZONE_BELOW_DAM; outside model watershed -> ZONE_BUFFER. Keep the None/all-ZONE_LAKE fallback when a polygon is missing. Rename to reflect the 3-way result (e.g. `_drainage_zone_array`).
1. CODE - target pools by zone: in build_drainage_mover_records (sfr.py:697-717) split targets into two labeled pools. lake_pool = reach cells of lake-coupled networks (703-706) PLUS the lake-footprint proxies (709-717). below_dam_pool = reach cells of the below-dam network(s) (route_drainage true AND outflow_to_lake None), with NO lake proxy. Keep provider_id/boundary_index alignment untouched (still single-period, 688-693).
1. CODE - zone-gated routing: in the loop (sfr.py:723-744) replace the binary buffer skip (727-731) with a zone branch keyed by the new array: ZONE_BUFFER -> continue (plain DRN out, as today); ZONE_LAKE -> nearest in lake_pool; ZONE_BELOW_DAM -> nearest in below_dam_pool (never a lake proxy). Emit the MoverRecord DRN->SFR (734-743) to the chosen reach ifno. Guard: if a ZONE_BELOW_DAM cell exists but below_dam_pool is empty, warn and leave it a plain DRN (do NOT fall back to the lake pool).
1. CODE - wire the call site: build.py:715-723 - pass the new zone array (rename kwarg watershed_cell_mask -> zone_by_cell), and make sure the below-dam SFR network is present in sfr_networks so its reaches populate below_dam_pool. Adjust the docstrings at sfr.py:658-684 and build.py:708-713 to describe three zones.
1. TESTS: add a unit test on build_drainage_mover_records asserting (a) a ZONE_BELOW_DAM centroid's MVR receiver is a below-dam reach ifno and never a lake-proxy terminal, (b) a ZONE_LAKE centroid still routes into the lake pool, (c) a ZONE_BUFFER centroid emits no record; plus a classifier test that a synthetic below-dam centroid lands in ZONE_BELOW_DAM. No tolerance changes.

**Risks:** "Missing lake sub-basin polygon: none is produced today; the whole Zone A/B distinction depends on delineating it at the dam. A bad pour-point snap (snap_dist) mis-places the A/B boundary, so the delineation must be QC'd against the dam axis / reservoir footprint. Missing polygon must degrade to today's behavior (all in-watershed -> lake), not crash.\n\nNo downstream reach exists (deliberately removed, project.toml:64-66): until one is added, Zone B has no valid target. The code must NOT silently route Zone B to the lake pool when below_dam_pool is empty; the only correct fallback is plain DRN 

### seam group

**Current:** HMP delineates exactly ONE watershed per model, from geographic.catchment. The path for catch_def="from_outlet_coord":

1. Config: OutletCatchDef (geographic_config.py:85-117) carries x_outlet/y_outlet/snap_dist/buff_area; it is one variant of the CatchDef discriminated union (geographic_config.py:147-151). GeographicConfig exposes them as properties (geographic_config.py:376-393).

2. Pipeline: build_geographic_runtime_context (pipeline.py:401-541) first builds the regional flow rasters (build_regional_flow_products → dem_breach/fill.tif, dem_direc.tif D8 pointer, dem_acc.tif D8 accumulation, all under geographic.correcflow_path), then for a non-DEM catch_def calls build_standard_catchment (pipeline.py:459-470).

3. build_standard_catchment (pipeline_steps.py:93-145) dispatches from_outlet_coord to extract_catchment_from_point.

4. extract_catchment_from_point (catchment_from_point.py:46-179) is the core primitive: writes an outlet.shp point, snaps it to the strongest-flow cell within snap_dist on dem_acc (snap_pour_points), delineates the watershed raster from dem_direc (watershed), then polygonizes to watershed.shp. The whitebox backend implements snap_pour_points / watershed / raster_to_vector_polygons (delineation.py:13-69).

5. build_standard_domain_polygons (pipeline_steps.py:148-166 → catchment_domain.py) buffers that single polygon into watershed_buff.shp, watershed_box.shp, watershed_box_buff.shp.

The resulting polygon is carried downstream as the FILE geographic.w 

**Seams:**
- `hydromodpy/spatial/geographic/core/catchment_from_point.py` 46-179 - Core outlet->watershed primitive (snap_pour_points -> watershed -> polygonize). Reuse verbatim to delineate the lake sub-basin from a lake-outlet point.
- `hydromodpy/spatial/geographic/subbasin.py` 34-211 - Existing, unwired sub-basin-from-arbitrary-XY machinery (extract_interest_zones); the template for a lake sub-basin step.
- `hydromodpy/spatial/geographic/pipeline.py` 459-482 - Where the single model watershed is delineated; where a second lake-subbasin delineation call and its persistence/caching would hook in.
- `hydromodpy/spatial/geographic/geographic_paths.py` 14-91 - Canonical path container; add lake_subbasin_shp beside watershed_shp so it rides runtime_attributes to model.geographic.
- `hydromodpy/workflow/steps/data.py` 203-345 - bind_sfr_network_traces: a run-time step that already holds geographic + lake polygons; the natural place to compute the lake outlet + delineate the lake sub-basin once.
- `hydromodpy/solver/modflow6/build.py` 187-218, 706-725 - _watershed_drainage_mask + the build_drainage_mover_records call site; add a sibling _lake_subbasin_mask and pass a new lake_subbasin_cell_mask.
- `hydromodpy/solver/modflow6/builders/sfr.py` 629-744 - watershed_drainage_cell_mask + build_drainage_mover_records; THE routing decision. Gate the lake-footprint proxy targets (697-717) per-cell so a DRN cell outside the lake sub-basin routes only to reaches (downstream river).
- `hydromodpy/physics/flow/structure_binders.py` 230-269 - apply_lake_geometry_to_flow attaches the lake footprint polygon used to locate the lake outlet.
- `hydromodpy/spatial/geographic/core/sfr_network.py` 392-431 - rasterio.open + features.rasterize pattern to reuse for burning the lake polygon onto dem_acc and finding the argmax outlet cell / co-registered masks.
- `hydromodpy/spatial/geographic/geographic_config.py` 85-117, 299-310 - OutletCatchDef fields (the delineation inputs) and domain_extent doc confirming the mask acts via DRN routing, not idomain; any new config field must be declared (extra=forbid).

**Change plan:**
1. Add a lake-outlet finder. New helper (e.g. spatial/geographic/core/lake_outlet.py) that, given a lake footprint polygon + geographic.correcflow_path rasters, returns the spill cell: rasterize the polygon onto dem_acc.tif (features.rasterize, pattern at sfr_network.py:392-431), take the argmax-accumulation cell inside the footprint (the thalweg), step one D8 cell downstream via dem_direc to the exit, and return its map (x,y). Provide a fallback = min-elevation cell on the polygon boundary sampled from dem_breach/fill.tif. Allow an explicit override (config x/y, or an 'outlet' point read from the lake_geometry vector file per config.py:21).
1. Delineate the lake sub-basin by calling the existing extract_catchment_from_point (catchment_from_point.py:46-179) with x_outlet/y_outlet = the found lake outlet, snap_dist from config, acc_path/direc_path = the SAME dem_acc.tif/dem_direc.tif under geographic.correcflow_path (so it is co-registered with the model watershed), writing lake_subbasin.shp into geographic_path. Do NOT re-run flow-accumulation; reuse the regional rasters exactly as Subbasin.extract_interest_zones does.
1. Persist the new polygon: add lake_subbasin_shp to GeographicPaths (geographic_paths.py) and to GeographicRuntimeContext.runtime_attributes (pipeline.py:81-101) so it lands as model.geographic.lake_subbasin_shp; add it to the geographic cache required-artifacts/manifest and fold the lake outlet into _geographic_cache_fingerprint (pipeline.py:125-141) so toggling re-delineates.
1. Trigger the delineation once at run time. Mirror bind_sfr_network_traces (workflow/steps/data.py:264-345): a step that already has setup_state.geographic + the bound lake polygons runs steps 1-2 and sets geographic.lake_subbasin_shp. Gate it on lakes being active so non-lake models are untouched.
1. Solver wiring: add _lake_subbasin_mask(model, centroids) beside _watershed_drainage_mask (build.py:187-218), reading geographic.lake_subbasin_shp via watershed_drainage_cell_mask (sfr.py:629-648, reuse as-is). Pass it as a new lake_subbasin_cell_mask argument into build_drainage_mover_records (build.py:722).
1. Change the routing decision in build_drainage_mover_records (sfr.py:651-744): keep watershed_cell_mask as the outer gate (buffer cells stay plain DRN, unchanged). For a DRN cell that IS in the watershed but is OUTSIDE the lake sub-basin (below-dam strip), build its nearest-target search over the REACH targets only, excluding the lake-footprint proxy targets added at sfr.py:709-717, so it routes to the nearest downstream reach. Cells inside the lake sub-basin keep the full target set (reaches + lake proxies). Still emit a record for every routed cell so provider_id = boundary_index alignment (the single-period static-DRN contract, sfr.py:686-693) is preserved.
1. Config surface: because extra=forbid, add an explicit opt-in field (e.g. a lake_subbasin_routing / lake_outlet override under the flow lake config or geographic) with a Field description and default that keeps today's behavior when unset. Document units/CRS inline.
1. Tests + diagnostics: unit test that a below-dam cell resolves to a downstream reach (not the lake) once the lake sub-basin mask is present; extend the existing 'watershed DRN mask' log (build.py:212-217) to also report lake-subbasin cell count; optionally surface both polygons in the catchment/id-card figures.

**Risks:** "extra=forbid: any new config knob must be an explicit declared field or validation raises. The MVR provider-id contract (single-period static DRN, sfr.py:686-693) must hold: only restrict target SELECTION, never reorder/renumber the DRN rows; still emitting a record per routed cell keeps provider_id=boundary_index aligned (same discipline as the current buffer-skip). Co-registration: the lake sub-basin MUST be delineated on the same dem_acc/dem_direc under correcflow_path as the model watershed, or the two per-cell masks will not line up. Outlet auto-detection is heuristic (argmax-accumulatio 


---
## 2026-07-08 addendum: dam geometry issue + voile elevation fix (from user review of diagnostic figures)

Diagnostic figures (tools/diagnostics/cheze_mf6_diagnostics.py, run against a `--until ExtractStep`
kept solver dir) surfaced THREE issues, all confirmed:

1. Flow arrows: fixed to show EVERY active cell (normalized direction, log-mag colour) by mapping
   DATA-SPDIS by its `node` field (SPDIS lists only active cells; naive reshape is wrong).
   figures/diagnostics/diag_flow_arrows_v2.png.

2. Voile POSITION wrong: the cutoff-wall line (331142,6780439)-(331119,6780719) sits +103 m WEST of
   the reservoir's east edge; 3 of its 4 cells are LAKE cells and 2 of 3 HFB faces are lake<->lake,
   i.e. the wall is INSIDE the reservoir, not at its downstream edge.

3. Voile ELEVATION wrong (fundamental): bathymetry reservoir_cheze.tif caps at 87.6 m and reads
   85-86 m at the wall = the ANTHROPIC DAM CREST, not the natural valley floor. bed_reconstruction
   (dynamic_area marnage) carves the aquifer top of lake cells to that bathymetry, so top at the wall
   = 86.5 m. The voile is realised 86.5->71.4 m (INSIDE the dam/water), ~30 m too high. Natural valley
   floor / dam base ~50 m (DEM min) ; user spec: voile TOP = 51 m (above it = the dam body), curtain
   51 -> 41 m (10 m). Downstream river ~41 m.

KEY ABACUS-SAFETY FINDING: lowering the dam-cell aquifer top to 51 m does NOT break the abacus. The
reservoir storage comes from the LAK `.laktab` tabfile (the abacus), NOT the carved cell geometry
(builders/lake.py:238-259). The carved bed only sets the LAK connection belev + the area_scale
diagnostic. So the dam-zone top carve is clean re: storage/calibration (KGE 0.77 unaffected).

FIX PLAN (abacus-safe), user-approved:
- Auto dam axis: anchor = reservoir cell nearest the model outlet (spill point), axis PERPENDICULAR
  to the local outlet-flow direction (outlet - spill), length = local reservoir width within ~150 m
  of the spill (prototype: spill (331063,6780912), 183 m axis, figures/diagnostics/dam_axis_auto.png).
  Ambiguity remains; a user-supplied dam axis is more reliable. Mesh dam_cell_size refinement must
  follow this auto axis.
- Carve dam-zone aquifer top to 51 m (natural valley floor) + regrade botm; abacus-safe.
- HFB voile referenced to ABSOLUTE elevation (top 51 m, foot 41 m) instead of depth-from-cell-top:
  patch build_flow_barrier_hfb barrier_bottom (flow_barrier.py:90) to accept an absolute top/foot.
- Verify: voile cross-section top=51 m, storage NSE ~0.98 unchanged, faces at the downstream edge.
