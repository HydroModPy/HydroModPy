# Roadmap

## v0.4 — Refactored architecture (imminent)

End of the 13-phase migration (P01–P13) plus the finalization phases
(F01–F07). This is a **breaking release**; see the full list of
breaking changes and the Migration Guide in `CHANGELOG.md`.

Highlights:

- Unified Simulation Catalog (one `hydromodpy.duckdb` + one Zarr store
  per simulation).
- `[display]` TOML section replaces `HYDROMODPY_NO_DISPLAY` /
  `HYDROMODPY_NO_SAVE` env vars.
- `catalog.export_package` / `catalog.import_package` (renamed from
  `export_simulation` / `import_simulation`).
- Simplified declarative `[calibration]` section; Optuna is the default
  optimizer, with a lightweight mode for fast local sweeps.
- SIM2 client renamed to `sim2_meteofrance` (data source: Meteo-France
  SAFRAN-ISBA surface reanalysis). Endpoint unchanged.
- Pipeline orchestration primitives: `PipelineState`,
  `CheckpointStore`, `StepsLedger`, `DerivedRegistry` — resume after
  crash is now a first-class feature.
- Glossary + design patterns under `docs/developers/` kept in sync
  with the code.

## v0.5 — Lake module integration (MF6)

Planned after v0.4 ships.

- **MF6 Lake (LAK) package** integration for shallow-groundwater /
  surface-water coupling. Unblocks the NWT sunset path.
- **NWT sunset begins.** The duplication between
  `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  and `hydromodpy/solver/modflow6/flow_to_modflow_adapter.py` is left
  in place during v0.4 but will be factored once all NWT scenarios
  have an MF6 counterpart (including lakes). See
  `docs/developers/nwt_sunset_plan.md`.
- Documentation rewrite targeting external users (beyond the core
  research group), including end-to-end tutorials.

## v0.6 — NWT removal + PEST++ adapter

Planned after v0.5.

- **MODFLOW-NWT removal.** The `hydromodpy/solver/modflow_nwt/` tree is
  deleted along with NWT-specific configs, golden references, and the
  `@pytest.mark.nwt` marker.
- **PEST++ / pyemu optional adapter** exposed via the
  `hydromodpy.optimizer` entry-point group. Kept optional to avoid
  forcing the PEST toolchain on users who only need Optuna or the
  built-in SciPy optimizers.

## Calibration (current status)

The P09 calibration package (`hydromodpy/calibration/`) ships with the
following optimizer adapters:

| Name                  | Library  | Notes                                   |
|-----------------------|----------|-----------------------------------------|
| `optuna`              | optuna   | TPE (default), CMA-ES, NSGA-II, Random  |
| `scipy_de`            | scipy    | differential evolution                  |
| `scipy_nelder_mead`   | scipy    | Nelder-Mead simplex                     |
| `grid`                | built-in | deterministic grid over bounds          |

Third-party optimizers (PEST++, dakota, ...) plug in through the
`hydromodpy.optimizer` entry-point group. The PEST++ adapter is
tracked as a v0.6 deliverable.
