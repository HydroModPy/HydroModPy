# catchment/terrain

This package routes water over a DEM. It removes the depressions that stop a cell from draining, writes the D8 flow
pointer and the flow accumulation, picks the stream cells, and delineates the catchment of each outlet. The rest of
HydroModPy asks for these products through one small interface, the `TerrainEngine` port, so the flow-routing library
behind it can change. Two engines ship with the package, and a third party can add one without a patch.

## How the work flows

A caller (the preprocess chain, the regional flow job) never builds an engine by name. It
asks the registry for an `engine_id`, then calls the five steps of the port in order.

1. The registry (`registry.py`) resolves the `engine_id` to a class and builds it. A caller that names none gets
   `whitebox_workflows`.
2. `condition_dem` fills or breaches the depressions of the DEM.
3. `drainage_directions` writes the D8 pointer, and `flow_accumulation` writes the accumulation in declared units.
4. `stream_network` keeps the cells above a threshold.
5. `delineate` snaps each outlet inside its window and writes its mask and boundary.

```text
geographic.terrain_engine / request "engine"
        |
        |  registry.py             name to class: built-in paths, then the entry-point group
        v
   TerrainEngine                   port.py
        |
        +-->  numpy_engine.py      numpy_d8, a plain reference engine
        +-->  whitebox_engine.py   whitebox_workflows, through catchment/delineation
```

Every product carries its own description (units, transform, pointer convention). So an accumulation stored as a
natural logarithm cannot be read as a cell count by mistake, and `stream_network` refuses it.

## The folder map

The package is flat. The port stands alone, and each engine and helper reads it.

```text
terrain/
├── port.py             the TerrainEngine Protocol, the product types and the checks an engine shares
├── registry.py         engine_id to engine class, and the entry point group
├── artifacts.py        readbacks of the files an engine wrote, and the writer of the two point layers
├── d8.py               the receiver of each cell of a D8 pointer raster
├── numpy_engine.py     NumpyTerrainEngine, priority flood and a topological sweep
└── whitebox_engine.py  WhiteboxTerrainEngine, delegates to the Whitebox backend
```

`__init__.py` holds only a docstring and exports no name. A caller imports the port from `port.py`, for example
`from hydromodpy.catchment.terrain.port import Outlet`, and an engine from its own module. Importing the package never
loads `whitebox_workflows`, because only `whitebox_engine.py` reaches it.

## Where to start

| To change | Open first |
|-----------|------------|
| what an engine must provide, or a product field | `port.py` |
| the accumulation units, the transforms, the snap window | `port.py` |
| how an engine is found, or what the registry refuses | `registry.py` |
| the default engine | `DEFAULT_ENGINE_ID` in `registry.py` |
| how a mask or a boundary is read back | `artifacts.py` |
| the columns of the two outlet point layers | `OUTLET_LAYER_COLUMNS` in `port.py`, `write_outlet_point` in `artifacts.py` |
| the Whitebox calls and the capped breach report | `whitebox_engine.py` |
| the reference engine | `numpy_engine.py` |
| the flow direction of a pointer cell | `d8.py` |

## Rules between the folders

The port is the only module a third-party engine has to know, so it imports almost nothing.

- `port.py` imports only `hydromodpy.core.exceptions`.
- `registry.py` reads `port.py`, `core.exceptions` and `core.logging`.
- `artifacts.py` and `d8.py` read `port.py`. `artifacts.py` also reads `core.exceptions` and `core.io.crs`.
- `numpy_engine.py` reads `port.py`, `artifacts.py` and the `core` modules `exceptions`, `io.crs`, `io.raster_io` and
  `nodata`.
- `whitebox_engine.py` reads `port.py`, `artifacts.py` and the `core` modules `exceptions`, `io.crs` and `logging`.
- The package imports no other layer, and no other part of `catchment`, with one exception. `whitebox_engine.py` asks
  `hydromodpy.catchment.delineation` for the Whitebox backend, inside `WhiteboxTerrainEngine.__init__` and only when the
  caller passes none. So a third-party engine, and the numpy engine, never load that module.
- The registry imports an engine module on the first lookup of its name, not at import time. The registry holds the
  built-in paths itself and has no entry in `pyproject.toml` for them.

`tests/unit/architecture/test_terrain_port_stands_alone.py` checks all of this. It allows `hydromodpy.core` and this
package, and it lists the one exception above. The layer matrix sees `catchment` as one layer, so it cannot check it. `catchment_layout.yaml` orders the parts and lets `terrain` read `delineation`.

## What lives outside the package

The callers pick the engine through the registry. `hydromodpy/catchment/algorithms/flow_products.py` and
`hydromodpy/catchment/preprocess/regional_flow_job.py` build it, and `preprocess/geographic_config.py` checks that
`geographic.terrain_engine` names an engine the installation serves. The Whitebox calls themselves are in `hydromodpy/catchment/delineation/`.

A third party registers an engine in the entry point group `hydromodpy.terrain.engine`. The entry point name must equal
the `engine_id` of the class, and a name that a built-in engine already uses is refused. A bad plug-in is skipped with a
warning, so it never stops a run that asked for another engine.

## Changing the code

The tests follow the layout of the code under `tests/unit/catchment/terrain/`. A file carries the name of the module it tests:
`test_port.py`, `test_registry.py`, `test_artifacts.py`, `test_numpy_engine.py` and `test_whitebox_engine.py`. `d8.py` has
no test file of its own and is tested through its callers. `tests/_helpers/terrain_doubles.py` builds terrain products
from bare paths for the tests that never read a DEM.

Four more checks guard the package.

- The engine contract, `tests/contract/test_terrain_engine_contract.py`, runs the same assertions on every engine the
  registry resolves, on files it writes on disk. A plug-in author runs it on their engine, without naming it in a test.
- `tests/contract/test_terrain_conformance_reaches_an_installed_engine.py` installs a probe engine and checks that the
  contract reaches it.
- `tests/unit/architecture/test_terrain_port_stands_alone.py` guards the imports of the port.
- `tests/unit/architecture/test_terrain_engine_imports.py` checks that each call site of a flow builder passes the engine
  on.

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of this package drops below 94.6,
the floor of the line `coverage report --include='hydromodpy/catchment/terrain/*'`. The floors only go up.

```bash
pytest tests/unit/catchment/terrain -q
```

```bash
pytest tests/contract/test_terrain_engine_contract.py tests/unit/architecture/test_terrain_port_stands_alone.py -q
```

A new member of the port is a method of the Protocol in `port.py`. Both engines must then serve it, because the contract
runs on both. A new engine is a class with `engine_id`, `engine_version` and the methods of the port. Raise
`engine_version` whenever its products change for one request.

## Documentation

No developer page is written for this package. The parameter that selects an engine is generated from the code:
`geographic.terrain_engine` in `docs/source/reference/parameters/geographic.md`. The gate that keeps the port free of other parts of `catchment`
is explained in `docs/source/contribute/architecture/how-to/fix-an-architecture-gate.rst`.
