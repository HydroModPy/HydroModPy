# data/loading

This folder turns the `[data]` section of the TOML into data in memory. It checks the section,
decides which variables to load, and calls their managers.

## The path of a load

1. `config_schema.py` validates `[data]` as `DataManagersConfig`. Each typed section
   (`[data.hydrometry]`, `[data.dem]` and so on) is read with the config class that
   `VARIABLE_SPECS` names for it.
2. `planner.py` (`DataPlanner`) builds the plan: the variables listed in `[data].types`, plus the
   ones another section implies, such as the rain and the evapotranspiration the soil reservoir
   reads. The plan is an immutable `DataLoadPlan` (`plan.py`).
3. `loader.py` (`DataManagersRuntimeLoader`) runs the plan inside a project run. For each variable
   it builds the manager from `VARIABLE_SPECS`, gives it the extent and the period, and collects
   the `LoadResult`.
4. `store.py` (`DataStore`) is the same thing for a user who loads data by hand, outside a project.

## The folder map

```text
loading/
├── _dispatch.py      VARIABLE_SPECS: for each variable, its config class and its manager class
├── config_schema.py  DataManagersConfig, the [data] section, and its checks
├── planner.py        which variables a run activates
├── plan.py           DataLoadPlan, the answer of the planner
├── loader.py         the loader of a project run
└── store.py          DataStore, the loader of a user
```

## Adding a variable

`VARIABLE_SPECS` is the one list that names the classes, as text paths so that nothing is imported
before it is needed. A variable still needs a field in `DataManagersConfig`, an entry in
`SUPPORTED_DATA_MANAGER_TYPES`, a field of `LoadedDataContext`, a row of the workspace scaffold
and, for a provider, an entry in `schema/sources.py`.
`tests/unit/data/test_the_variable_families_agree.py` names the list you missed. The full recipe
is `docs/source/contribute/architecture/how-to/add-a-data-variable.rst`.

## Rules

- The JSON schema of `[data]` is pinned by `tests/unit/data/test_the_data_surfaces_hold_still.py`.
- Nothing here imports a manager at module level. `VARIABLE_SPECS` holds paths as text.

## Changing the code

The tests are in `tests/unit/data/loading/`.
