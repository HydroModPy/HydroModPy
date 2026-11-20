# data

Everything a run reads from outside is here: provider APIs, the files of the user, their cache and the typed records handed to the layers above. Each `[data.<name>]` section of a project TOML is one variable, and `VARIABLE_SPECS` in `loading/_dispatch.py` is the one list of them. A variable owns its cache and the unit of its records and leaves the provider to a class of the `DataSource` port (`source/`, with its own README), so adding a provider touches no variable. The data folder is the cache, each fetched file has a JSON sidecar beside it, and there is no database. The package is a layer because the loaders, the workflow and the calibration need data in one typed form, and none of them should know which provider or file it came from.

A run loads data through `loading/` (`DataConfig`, `DataPlanner`, `DataLoader`), and a user loads it by hand with `DataStore`. A request from outside a project goes through `request/` and `hmp data get`. Every load ends in a `LoadResult` of point, field and table records. They carry the unit of the provider, and `core/units` converts to SI at the entry of the model.

The package reads `core`, `schema`, `catchment`, `mesh` and `model`, and never `results`. It is read by `config`, `calibration`, `workflow`, `project`, `cli` and the root facade. The twelve subpackages are ordered in `tests/unit/architecture/data_layout.yaml`, and `test_package_layouts.py` checks every import.

The page of the package lists its modules with the first line of their docstring. It also gives the template of a variable, the rules between the subpackages, the cache, the site catalog and where to add what.
