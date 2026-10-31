# spatial/delineation

This package holds the tools that read a DEM and give back flow products: filled DEMs, D8 pointers, accumulations, pour
points, watersheds and stream networks. It has one backend, Whitebox Workflows, wrapped in a few classes with the
same names for the same operations. A small registry hands out the backend, so the rest of the code asks for "the
delineation backend" and never imports `whitebox_workflows` itself.

## How the work flows

1. A caller asks the registry (`registry.py`) for a backend, with `get_backend` or `resolve_delineation_backend`.
   The registry imports the backend only now, and keeps one instance for the process.
2. The backend is a facade, `WhiteboxWorkflowsBackend`, with three parts: `raster` for files and the shared Whitebox
   environment, `flow` for depressions, pointers and accumulation, and `delineation` for pour points, watersheds and
   streams.
3. The three parts run their tools in the same Whitebox environment, so they read and write the same rasters.
4. Depression removal runs in a child Python process. Whitebox 1.3.5 can end the process that calls it, with no
   exception, when two of its threads race. The child dies instead, and the parent runs it again, three attempts in all.

```text
caller (geographic, site selection, solver routing)
        |
        |  registry.py                       name to backend class, one instance
        v
   WhiteboxWorkflowsBackend                  whitebox_workflows_backend/__init__.py
        |
        +-->  .raster       file IO, nodata, clipping, rasterising
        +-->  .flow         depressions, D8 pointer, accumulation
        |        |
        |        +-->  isolated.py ----> depression_child.py   (child process)
        +-->  .delineation  pour points, watersheds, streams
```

The terrain package (`hydromodpy/spatial/terrain/whitebox_engine.py`) sits on top of this backend and offers the
interface the callers prefer.

## The folder map

```text
delineation/
├── registry.py                     backend name to backend class, aliases, extra backends
└── whitebox_workflows_backend/     the Whitebox Workflows backend
    ├── raster.py                   WhiteboxRasterBackend, the environment, file IO and raster tools
    ├── component.py                what the flow and delineation parts share with the raster part
    ├── flow.py                     WhiteboxFlowBackend, depressions, pointer, accumulation
    ├── delineation.py              WhiteboxDelineationBackend, pour points, watersheds, streams
    ├── isolated.py                 run a depression tool in a child process, and retry the race
    └── depression_child.py         the script the child runs, imports no HydroModPy module
```

`__init__.py` of `delineation/` gives the backend classes and `get_whitebox_backend` through lazy imports, so
`import hydromodpy.spatial.delineation` never loads Whitebox. The `__init__.py` of `whitebox_workflows_backend/` defines
the facade `WhiteboxWorkflowsBackend` and `get_whitebox_backend`, which returns the instance of the registry.

## Where to start

| To change | Open first |
|-----------|------------|
| the backend that a name resolves to, or an alias | `registry.py` |
| add another backend | `register_backend` in `registry.py` |
| how a raster or a vector is read or written | `whitebox_workflows_backend/raster.py` |
| the Whitebox messages on screen | `silence_stdio` in `whitebox_workflows_backend/raster.py` |
| filling, breaching, D8 pointer or accumulation | `whitebox_workflows_backend/flow.py` |
| snapping a pour point, a watershed or streams | `whitebox_workflows_backend/delineation.py` |
| the crash of Whitebox on a depression tool | `whitebox_workflows_backend/isolated.py` |

## Rules between the folders

- `registry.py` imports no other module of HydroModPy. It names the backend class by a dotted path and imports it on the
  first lookup, so importing the registry never loads `whitebox_workflows`.
- `raster.py` and the child script `depression_child.py` are the only modules that import `whitebox_workflows`.
  `raster.py` also reads `hydromodpy.core.progress`.
- `component.py` reads `raster.py`, `isolated.py` and `hydromodpy.core.progress`. `flow.py` and `delineation.py` read
  `component.py` and `raster.py`.
- `isolated.py` reads `core.exceptions` and `core.logging`. `depression_child.py` is run by path and never imported.
  It imports nothing from HydroModPy, so the child starts fast.
- `whitebox_workflows_backend/__init__.py` reads the registry to share one instance. The registry loads the backend
  class through a string, so there is no import cycle.
- The package imports no layer above `core`.

The layer matrix is checked by `tests/unit/architecture/`.

## What lives outside the package

The users of the backend are in `hydromodpy/spatial/geographic/` (the pipeline, the catchment delineation, the river
network), in `hydromodpy/spatial/site_selection/candidates/generation.py`, in `hydromodpy/data/variables/hydrography/`,
in `hydromodpy/solver/modflow_common/` and `modflow_nwt/modpath/`, and in `hydromodpy/workflow/steps/export.py`. They
call `resolve_delineation_backend` or `get_whitebox_backend`, or take a backend as an argument. The terrain engine
`WhiteboxTerrainEngine` in `hydromodpy/spatial/terrain/` calls it through `get_whitebox_backend`.

## Changing the code

The tests are in `tests/unit/delineation/`. `test_registry.py` tests `registry.py`. The folder
`tests/unit/delineation/whitebox_workflows_backend/` holds `test_whitebox_workflows_backend.py` for the facade and its
three parts, `test_whitebox_depression_child.py` for the child process and its retry, and
`test_delineation_determinism.py` for the stability of the results.

The CI runs `test_whitebox_workflows_backend.py` in its own step, apart from the rest of the suite
(`.github/workflows/main-ci.yml`). The job `mesh-coverage` fails when the coverage of this package drops below 97.2,
the floor of the line `coverage report --include='hydromodpy/spatial/delineation/*'`. The floors only go up.

```bash
pytest tests/unit/delineation -q
```

A new Whitebox tool is a method of the part it belongs to. It comes as a pair, a `*_raster` or `*_vector` method that
works on objects in memory and a method that reads and writes files. Only a depression tool that can end the process
goes to `DEPRESSION_TOOLS` in `isolated.py`.

## Documentation

`docs/source/contribute/architecture/contracts.rst` describes the registry in its section on the delineation backend.
The class that drives the backend for a catchment, `CatchmentDelineation`, is in
`docs/source/reference/python/CatchmentDelineation.md`.
