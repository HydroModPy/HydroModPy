# `hydromodpy/config`

The root of the configuration. `HydroModPyConfig` is the one Pydantic model that
aggregates every section of a project TOML. Anything a user can write in a project
file must load through it and round-trip. This file is the map of the package:
what is here, which section is owned by which package, how a TOML becomes a
validated object, and where to add what.

The package is thin on purpose. Each section model lives next to the code it
configures. The composition root is the only place where the section types of
the other packages are imported together; every other layer refers to its own
section model, never to the root.

## Parts

| part | answers |
|---|---|
| `hydromodpy_config.py` | what is a whole project file? `HydroModPyConfig` (the root), `WorkflowConfig` (the `[workflow]` section), the loading entry points `from_toml`, `from_dict`, `from_json`, `from_snapshot`, and the cross-section checks |
| `toml_section_loader.py` | how is one raw section turned into its model, with paths resolved against the project root? `load_standard_section`, `load_geographic_section` |
| `sites/` | the `[sites]` section and the plan of a campaign: `models.py` (the section as the TOML declares it), `expansion.py` (`expand_plan`: sites x recipes into cases, the precedence of a case, the site scoped keys, the origin of every error), `plan.py` (`write_plan_draft`: `plan/<hash>/` written once), `budget.py` (what a plan costs, the `--dry-run` lines, the ceilings), `check.py` (`check_project`, the one check behind `hmp config check`), `single_site.py` (a `[site]` resolved against the site catalog of the workspace) |
| `metrics_config.py`, `publication_config.py` | the `[metrics]` and `[publication]` root sections |
| `config_migration.py` | how does a file written against an earlier schema still load? `migrate_config_doc_on_load` rewrites the parsed payload in memory; `fix_config_file` (called by `hmp doctor --fix-config <file>`) rewrites the file in place. `RENAMED_KEYS` lists the keys a loader refuses under an old name: the doctor renames them, and `migrate_sealed_config_doc` renames them on read in the frozen config of a run on disk |
| `schema_export.py` | the JSON Schema of the root or of one section, filtered by profile (`export_schema`, `write_schema`, `schema_sha256`) |
| `dynamic_flow_examples.py` | the provider that lets the TOML template generator render commented examples for the dynamic `[flow.param.*]`, `[flow.bc.*]` and `[flow.sinks_sources.*]` blocks without importing `physics` or `spatial`. `hydromodpy/_bootstrap.py` wires it |

`from hydromodpy.config import HydroModPyConfig` resolves the class lazily, so
importing the package loads no model.

## Sections of the root

One field of `HydroModPyConfig` per top-level TOML section. Required: `workflow`,
`workspace`, `geographic`. The others have a default or are optional.

| section | model | defined in |
|---|---|---|
| `[workflow]` | `WorkflowConfig` | `config/hydromodpy_config.py` |
| `[workspace]` | `WorkspaceConfig` | `core/workspace/config.py` |
| `[geographic]` | `GeographicConfig` | `spatial/geographic/` |
| `[domain]` | `DomainConfig` | `spatial/domain/` |
| `[data]` | `DataManagersConfig` | `data/loading/config_schema.py` |
| `[flow]` | `FlowConfig` | `physics/flow/` |
| `[transport]` | `TransportConfig` | `physics/transport/` |
| `[simulation]` | `SimulationConfig` | `simulation/planning/config.py` |
| `[solver]` | `SolverConfig` | `solver/base/solver_config.py` |
| `[modflownwt]` | `ModflowConfig` | `solver/modflow_nwt/nwt/nwt_config.py` |
| `[modflow6]` | `Modflow6Config` | `solver/modflow6/modflow6_config.py` |
| `[display]` | `DisplayConfig` | `display/config.py` |
| `[[export]]` | `ExportRequest` (a list) | `core/config_kit/export_spec.py` |
| `[observation]` | `ObservationConfig` | `simulation/planning/observation_config.py` |
| `[overview]` | `OverviewConfig` | `display/overview/config.py` |
| `[mesh]` | `MeshConfig` | `spatial/mesh/mesh_config.py` |
| `[calibration]` | `CalibrationConfig` | `calibration/config.py` |
| `[spinup]` | `SpinupConfig` | `simulation/spinup_config.py` |
| `[site]` | `SiteConfig` | `core/site/config.py` |
| `[sites]` | `SitesConfig` | `config/sites/models.py` |
| `[metrics]` | `MetricsConfig` | `config/metrics_config.py` |
| `[publication]` | `PublicationConfig` | `config/publication_config.py` |

`[workflow].mode` is one of `simulation`, `calibration`, `overview`
(`WorkflowMode`), and is optional: unset, the sections of the file say what
`hmp run` does (`workflow/dispatch.py`). A retired mode (`comparison`,
`testbed`) is refused with its replacement
(`RETIRED_WORKFLOW_MODES`). `[site]` and `[sites]` never coexist: a `[sites]`
project takes the site of each case from its table row.

The retired root sections `[analysis]` and `[hydrometry]` are refused by name with what replaces them
(`model_refused_keys`).

The generated reference of the sections is the TOML reference of the
documentation; it is built from these models.

## Invariants of a section model

Each model honors the rules of the project:

- it derives from `HydroModelBase` (`core/config_kit/base.py`), which sets
  `extra="forbid"` and `validate_assignment=True`, so a typo in a key is refused;
- each field is `Annotated` with a `Profile` (`USER`, `DEV` or `EXPERT`, in
  `core/config_kit/profile.py`) and, for a physical quantity, with a unit alias of
  `core/units`;
- each field has a `Field` description, which is the text of its card in the
  reference.

## How a TOML becomes a config

```
hmp run file.toml
  -> HydroModPyConfig.from_toml(path)
       core/toml_io/loader.load_toml_with_base_config   follows base_config, merges, detects cycles
       config_migration.migrate_config_doc_on_load      earlier schema, in memory, file untouched
       (optional) profile check                         a field above the asked profile warns
       _from_payload(raw, base=<project root>)          core/toml_io/loader.config_base_dir
         expand the calibration protocol
         refuse retired sections and unknown top-level sections
         parse [workspace] first                        its data folder serves every other section
         one loader per section                         relative paths resolved against the project root
         model_validate on the root                     cross-section checks run here
         name from the file name when [simulation].name is empty
```

The project root is the folder that holds `project.toml` at or above the file;
outside a project, the folder of the root file of the `base_config` chain. Every
relative path of every file of a project (`plan/<hash>/<case>.toml`,
`runs/<case>/config.toml`, `site_overrides/<site>.toml`) is read from it, so a
file two folders down names the same `dem_init_path` as `project.toml` does.

`from_dict` and `from_json` take the same road from a mapping or a JSON payload,
with `context="api"`. `from_snapshot` rebuilds a config from the JSON snapshot
stored with a run.

`[workspace].project_root` is never a key of a file: the loader sets it from
the location of the file (the environment variable `HMP_PROJECT_ROOT` wins);
an `api` payload defaults it to the base folder. A refusal leaves
`_from_payload` as a `ConfigValidationError` that names the section, never as a
bare Pydantic error.

## A campaign: `[sites]` x `[sites.recipes]`

`config/sites/expansion.expand_plan(project_root, config_path)` resolves one
case per (site, recipe): the site table (`[sites] table`, or the site catalog
of the workspace) rendered through `[sites.bind]`, `site_overrides/<site>.toml`,
the recipe's own keys, then `--set` and `HMP_SET_*`. Precedence, lowest first:
defaults < the base of the recipe < the rendered row < the site overlay < the
recipe's own keys (its file, its inline `set`, its row of `recipes_table`) <
`--set`. Each case is validated through `HydroModPyConfig.from_dict`, hashed
by `config_identity_hash` without `[workspace]`, and refused when a site scoped
key keeps a literal value (`config/sites/site_scoped.py`). An error names its
cell: `sites.csv:37 column x_outlet -> geographic.catchment.x_outlet: ...`,
grouped over the cases it touches. `plan.write_plan_draft` writes the plan once
under `plan/<hash>/` through `results/plan_store.py`; `budget.plan_budget`
gives the numbers of `hmp run --dry-run`; `check.check_project` is the one
check of `hmp config check` for a run, a calibration or a whole project.

Cross-section checks of the root (`_check_cross_section_coherence`), each refused
with a sentence:

- `data.inference_mode = "strict"` needs a non-empty `data.types`;
- a `domain.depth_model` of a raster kind reads `[data.substratum]`, which must
  be declared;
- a zonal `[modflownwt.sgrid.top_sampling]` needs `channel_source = "none"`;
- a declared `[data.soil_capacity]` needs `[flow.sinks_sources.recharge.soil]`,
  and that soil reservoir is checked against what it reads and where it runs: the
  precipitation and ETP sections it needs, no loaded `recharge` or `runoff`, the
  `modflow6` backend, a declared `[simulation.time]`, and its spin-up;
- `[calibration]` needs a non-empty `flow.param_list`, and `[transport]` is
  refused with the `boussinesq` backend;
- every declared boundary must be supported by the backend, and
  `flow.restart_from`, a `spinup_cyclic` initial condition, flow barriers and
  cutoff walls need a backend that declares the capability (a mismatch raises
  `IncompatibleCapabilitiesError`).

## Import rules

`config` imports `core`, `schema`, `physics`, `data`, `spatial`, `simulation`,
`solver`, `calibration`, `results`, `display`, `analysis`, `reporting` and
`workflow` (`tests/unit/architecture/layer_matrix.yaml`): every layer it
composes. The root facade, `schema`, `results`, `reporting`, `workflow`,
`project` and `cli` import it. `core` never imports it: a layer that needs a
section type takes it from its own package, or through a protocol of `core`
(`core/config_kit/root_config_protocol.py`).

## Where to add what

1. **A field in an existing section.** On that section's model, with a `Profile`,
   a unit alias when it is a quantity, and a description. The parameter
   reference is computed from the model at the next documentation build
   (`tools/docs/field_registry.py`). The committed JSON Schema,
   `docs/source/_static/hydromodpy-schema.json`, is compared with the model by
   `tests/unit/docs/test_docs_config_consistency.py`.
   `docs/source/contribute/architecture/how-to/add-a-config-field.rst` has the
   steps.
2. **A new top-level section.** A model in the package it configures, a field on
   `HydroModPyConfig`, and its entry in `section_loaders` of `_from_payload`.
3. **A renamed or moved key.** A rule in `config_migration.py`, so earlier files
   still load, with a test. A retired key is refused by the model with the key
   to write: no migration carries it.
4. **A retired section.** A refusal at the top of `_from_payload` that names the
   replacement.
5. **A cross-section rule.** `_check_cross_section_coherence`, only when the rule
   needs two sections; a rule on one section belongs in that section's model.

## Reading path

1. `hydromodpy_config.py`: the fields of the root, then `_from_payload`.
2. `core/toml_io/loader.py` for the `base_config` chain.
3. `core/config_kit/profile.py` and `introspect.py` for the visibility model.
4. One section model, for example `physics/flow/flow_config.py`.
5. `schema/export.py` and `config/schema_export.py` for what is exported to
   frontends and IDEs.
