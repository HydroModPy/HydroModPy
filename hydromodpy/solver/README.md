# solver

The numerical backends. `solver.backend` names the flow backend, the table `[solver.<name>]` holds its settings, and a `[[simulation.process]]` entry names the solvers each process runs. The package holds the adapters that turn a built `Flow` or `Transport` into a backend run, the extractors that read the backend's files into the results store, and the registry that pairs a `<process_type>_<name>` key with each. Four flow backends ship, MODFLOW 6, MODFLOW-NWT, Boussinesq and the linear reservoir, with the transport tools that go with them.

The package is a layer because every backend meets the rest of HydroModPy through one contract in `base/`. A layer above imports the registry from `solver/base/registry.py` and never a backend, so a backend can be added or replaced without touching it.

What a backend can do is declared on its adapter class, in the twelve attributes described in `base/README.md`. `writes` lists what it stores, `supports` the traits of the `Model` it honours and `category` how it resolves space.

The parts are `base/` (the shared contract, the plan and the runner), `modflow_grid/` and `modflow_common/` (what the two MODFLOW backends share), `modflow6/`, `modflow_nwt/`, `boussinesq/` and `linear_reservoir/`. Each backend folder has a README of its port.

`solver` reads `core`, `schema`, `catchment`, `mesh`, `model`, `results` and itself, as `tests/unit/architecture/layer_matrix.yaml` says. `workflow`, `config`, `calibration`, `cli`, `project` and the root facade read it.

The page `docs/source/contribute/architecture/packages/solver.rst` lists the modules and holds the import rules, how a run reaches a backend and where to add what.
