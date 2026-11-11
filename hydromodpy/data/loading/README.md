# data/loading

This folder turns the `[data]` section of the TOML into data in memory. It checks the section,
decides which variables to load, and loads each one through its variable class.

## The path of a load

1. `config_schema.py` validates `[data]` as `DataConfig`. Each typed section
   (`[data.hydrometry]`, `[data.dem]` and so on) is read with the config class that
   `VARIABLE_SPECS` names for it.
2. `planner.py` (`DataPlanner`) builds the plan: the variables listed in `[data].types`, plus the
   ones another section implies, such as the rain and the evapotranspiration the soil reservoir
   reads. The plan is an immutable `DataLoadPlan` (`plan.py`).
3. `loader.py` (`DataLoader`) runs the plan inside a project run. For each variable
   it builds the variable class from `VARIABLE_SPECS`, gives it the extent and the period, and collects
   the `LoadResult`.
4. `store.py` (`DataStore`) is the same thing for a user who loads data by hand, outside a project.

## The folder map

```text
loading/
├── _dispatch.py      VARIABLE_SPECS: for each variable, its classes and the columns of its folder
├── config_schema.py  DataConfig, the [data] section, and its checks
├── planner.py        which variables a run activates
├── plan.py           DataLoadPlan, the answer of the planner
├── loader.py         the loader of a project run
├── inputs.py         the user files and URLs a document declares, resolved before the run is registered
└── store.py          DataStore, the loader of a user
```

## Adding a variable

`VARIABLE_SPECS` is the one registry of the 28 variables. It names the config and variable classes
as text paths so that nothing is imported before it is needed, and it holds the columns of the
folder `data/<variable>/` that the workspace scaffold writes (category, kind, unit, label). The
tuple `DATA_VARIABLES` and the scaffold read it, they keep no list of their own. A variable still
needs a field in `DataConfig`, a field of `LoadedDataContext` and, for a provider, an entry in
`schema/sources.py`. A thin variable (a source class and a variable class, no code of its own)
goes in one of the flat modules of `variables/` (`sim2_series`, `forcing_series`, `lake_series`,
`user_rasters`), a rich one gets its own folder.
`tests/unit/data/test_the_variable_families_agree.py` names the list you missed. The full recipe
is `docs/source/contribute/architecture/how-to/add-a-data-variable.rst`.

## Rules

- The JSON schema of `[data]` is pinned by `tests/unit/data/test_the_data_surfaces_hold_still.py`.
- Nothing here imports a variable class at module level. `VARIABLE_SPECS` holds paths as text.

## Changing the code

The tests are in `tests/unit/data/loading/`.
