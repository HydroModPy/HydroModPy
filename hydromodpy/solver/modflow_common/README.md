# solver/modflow_common

What MODFLOW 6 and MODFLOW-NWT do the same way. A module that only one of them reads lives in that backend.

## Modules

1. The binaries. `binaries.py` finds, downloads and checks the MODFLOW executables and `libmf6`, keeps the manifest of the cache, and makes a bundled binary executable.
2. The run. `flow_adapter_helpers.py` is the life of a flow adapter: build, write, solve, read the listing. `progress.py` shows the solve while it runs. `options.py` holds the pre-processing, run and NWT post-processing options. `routing_context.py` and `raster_export.py` write the solver DEM and its D8 pointer.
3. The properties. `property_mapping.py` maps K, Kv, Sy and Ss on the solver mesh at its layer-center depths, through `model.properties.property_table`. `runtime_arrays.py` shapes the concentration overrides of a transport run.
4. The descent of the solver mesh. `flow_directions.py`, `channel_tree.py`, `catchment_basin.py`, `descent_store.py` and `discharge_routing.py` give the receiver of each cell, its channel network, its basin, the sidecar that stores them, and the per-cell discharge routed down.
5. The extraction. `time_units.py` reads the time unit a run declared, `period_steps.py` groups the saved steps by stress period, `budget_components.py` names the budget terms, `budget_policy.py` records what a budget extraction kept, `field_slab.py` bounds the slab of a field write, `sink_mask.py` marks the closed depressions, `boundary_roles.py` stores the role of each constant-head cell.
6. The calibration readers. `calibration_extractors.py` reads heads and budgets for a trial, and `observable_extraction.py` turns them into observables.
7. `mt3dms_extractor_base.py` is the concentration extractor that MT3DMS and MODFLOW 6 GWT share.

`modflow_common` imports `base` and `modflow_grid`, never a backend.
