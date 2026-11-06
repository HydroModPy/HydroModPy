# `hydromodpy/project/launch/sites`

The plan of a `[sites]` project. The section itself, as the TOML declares it, is
`SitesConfig` in `hydromodpy/config/sites.py`, because the root configuration reads
it. This folder turns that section into cases, one per site and recipe, writes the
plan once, and says what it costs. `hmp run --dry-run`, `hmp config check` and the
launcher of `project/launch/` read it.

## Modules, in the order a plan is built

| module | what it answers |
|---|---|
| `tables.py` | the site table read from CSV, Parquet or GeoPackage, with the origin of every cell (`read_table`, `table_from_site_rows`) |
| `binding.py` | the columns of the table bound to dotted keys by `[sites.bind]`, and a row rendered into a TOML fragment (`resolve_bindings`, `render_row`) |
| `site_scoped.py` | the keys that must differ from one site to the next, and the ones a case left literal (`literal_site_scoped_keys`, `leaf_paths`) |
| `issues.py` | a problem of one case, named at its cell or file, and grouped over the cases it touches (`PlanIssue`, `group_issues`, `PlanError`) |
| `expansion.py` | sites x recipes resolved into cases with their precedence, each validated by `HydroModPyConfig.from_dict` (`expand_plan`, `single_case_draft`, `PlanDraft`, `case_is_done`) |
| `plan.py` | the plan written once under `plan/<hash>/` through `results/plan_store.py`, and the cases still running (`write_plan_draft`, `running_cases`, `is_plan_case`) |
| `budget.py` | what a plan costs: solves, scratch, the lines of `--dry-run`, the ceilings (`plan_budget`, `dry_run_lines`) |

## Import rules

The folder sits in `project/launch/`, so it may import any layer. It reads `config`
(the section and the root model), `results` (the plan store, the run identity, the
seal of a run) and `data` (the site catalog of the workspace). It imports nothing
else of `project`, as `tests/unit/architecture/test_project_launch_and_exchange_stand_alone.py`
requires of `launch/`. A name is imported from the module that defines it.

## Where to add what

- A table format: `tables.py`, with the origin of its cells.
- A rule on a whole case (a key that must be site scoped, a budget ceiling): `site_scoped.py` or `budget.py`.
- A check of the section alone, without reading a file: `SitesConfig` in `config/sites.py`.
