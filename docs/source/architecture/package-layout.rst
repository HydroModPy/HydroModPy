Package Layout
==============

The Python package lives under ``hydromodpy/``. This page is the map
of every subpackage with one-line responsibilities and the
recommended starting file. For deeper reading, follow the link to the
matching :doc:`packages/index` entry.

Top-level facade
----------------

.. code-block:: text

   hydromodpy/
   |-- __init__.py             Lazy public exports plus PROJ bootstrap.
   |-- _api.py                 Top-level helpers (open, run, calibrate,
   |                           index, compare_pair, report,
   |                           audit_prune, doctor).
   |-- _bootstrap.py           PROJ database setup at import time.
   |-- _lazy.py                Lazy-export tables (LAZY_IMPORTS,
   |                           MODULE_EXPORTS).
   |-- __main__.py             ``python -m hydromodpy`` entry point.
   `-- project/                Public ``Project`` facade subpackage.
       |-- __init__.py         Re-exports ``Project`` and its helpers.
       |-- facade.py           ``Project`` class.
       |-- accessors.py        Read-only accessors on Project.
       |-- catalog.py          Project-level catalog binding.
       |-- phases.py           Lazy-phase Project orchestration.
       |-- runner.py           Project execution wrapper.
       `-- dispatch/           Workflow / calibration adapters bound to
                               ``Project`` (workflow.py, calibration.py).

The :class:`hydromodpy.project.Project` facade composes setup, data
loading, mesh construction, solver execution, and result ingestion.
Most user code only touches it.

Subpackages
-----------

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - Subpackage
     - Role and entry file
   * - ``analysis/``
     - Cross-run analysis: simulation comparison
       (``analysis/comparison/``) and testbed variants
       (``analysis/testbed/``, hosting the ``regional_lab`` profile).
       Start at ``analysis/__init__.py``. See :doc:`packages/analysis`.
   * - ``calibration/``
     - Ask/tell engine, parameter sets, objective dispatch, optimizer
       adapters (CmaEs, Optuna, RandomSearch, ScipyDE,
       ScipyNelderMead, Grid, GpMapping, DaMhGp), persistence,
       diagnostics, runnable cases. Entry: ``calibration/cli_runner.py``.
       See :doc:`packages/calibration`.
   * - ``catalog/``
     - Read-only view over the workspace data cache. The simulation
       catalog itself is opened with ``hmp.open`` (returns a
       ``SimulationCatalog``); the machine-wide index is reached via
       ``hmp.index()``. Entry: ``catalog/inputs.py``. See
       :doc:`packages/catalog`.
   * - ``cli/``
     - ``hmp`` and ``hydromodpy`` console entry points. One module per
       verb under ``cli/commands/``, registered through ``ALL_COMMANDS``
       in ``cli/commands/__init__.py``. See :doc:`packages/cli`.
   * - ``config/``
     - Root ``HydroModPyConfig`` Pydantic model that aggregates every
       TOML section. Entry: ``config/hydromodpy_config.py``. See
       :doc:`packages/config`.
   * - ``core/``
     - Kernel leaf with no sibling-layer dependency. Hosts unit
       aliases (``core/units``), ``Profile`` enum
       (``core/config_kit``), workspace resolver (``core/workspace``),
       canonical metrics (``core/metrics``), I/O helpers
       (``core/io``), runtime state (``core/state``), input-file
       tracking (``core/tracking``), and time helpers (``core/time``).
       See :doc:`packages/core`.
   * - ``data/``
     - Data managers per variable (``data/variables/``), source
       registry (``data/sources.py``), planner
       (``data/planner.py``), DuckDB cache
       (``data/registry/catalog_duckdb.py``), and load contracts
       (``data/contracts/``). 17 variables, several public APIs
       (Hub'Eau, BD TOPAGE, BRGM, IGN BD Alti, SHOM, SIM2). See
       :doc:`packages/data`.
   * - ``display/``
     - Solver-agnostic figures registered through
       ``display/catalog.py``. 33 named figures under
       ``display/figures/``, plus geographic helpers (``display/geo``)
       and overview rendering (``display/overview``). See
       :doc:`packages/display`.
   * - ``physics/``
     - Process layer. ``physics/base/`` defines ``ProcessSpatial``,
       ``physics/flow/`` and ``physics/transport/`` carry the concrete
       runtime objects, ``physics/forcing/`` aligns climate inputs,
       ``physics/hydrology/`` hosts PyHELP and synthetic helpers. See
       :doc:`packages/physics`.
   * - ``results/``
     - Workspace catalog (``results/catalog/``), per-run ``Run``
       facade (``results/run.py``), Zarr / Parquet writers,
       importers, and exporters (``results/exporters/``: csv, netcdf,
       geotiff, vtu, shapefile, hmp_package). See
       :doc:`packages/results`.
   * - ``schema/``
     - JSON Schema export and partial-field validator.
       ``schema/export.py`` writes ``config.json``,
       ``config_meta.json``, ``field_validators.json``;
       ``schema/partial_validator.py`` validates one field at a time.
       See :doc:`packages/schema`.
   * - ``simulation/``
     - Simulation orchestration. ``simulation/planning/`` builds an
       immutable ``SimulationPlan`` of ``ProcessRun`` units;
       ``simulation/execution/`` runs them; ``simulation/extraction/``
       ingests outputs into the catalog;
       ``simulation/adapters/`` hosts backend-agnostic helpers. See
       :doc:`packages/simulation`.
   * - ``solver/``
     - Backend abstraction (``solver/base/``) plus three concrete
       backends (``solver/boussinesq/``, ``solver/modflow6/``,
       ``solver/modflow_nwt/``). Shared helpers in
       ``solver/modflow_common/``, grid abstraction in
       ``solver/modflow_grid/``. Time helpers now live in
       ``core/time/``. See :doc:`packages/solver`.
   * - ``spatial/``
     - Spatial-support stack: ``spatial/delineation/`` (Whitebox
       backends), ``spatial/geographic/`` (DEM, watershed, river
       network), ``spatial/domain/`` (zones, depth model),
       ``spatial/mesh/`` (cartesian DIS plus Gmsh DISV),
       ``spatial/field/`` (FieldSpatial, FieldParam, HydroMesh
       pivot). See :doc:`packages/spatial`.
   * - ``workflow/``
     - Composable steps and the immutable ``PipelineState`` payload.
       ``workflow/internals/`` carries the ``Step`` protocol,
       checkpoint store, ledger, dependency resolver;
       ``workflow/steps/`` hosts the 12 canonical steps;
       ``workflow/pipelines/`` assembles them. See
       :doc:`packages/workflow`.
   * - ``project/``
     - Public object-oriented facade above the matrix. It binds
       workflow and calibration launchers to ``Project`` without
       making lower layers depend on the facade. Entry:
       ``project/facade.py``. See :doc:`packages/project`.
   * - ``validity_frame/``
     - Experimental observability tooling for runtime capture and
       JSONL-to-DuckDB ingestion. It is isolated from modeling layers
       and is not a stable V1 public API. See
       :doc:`packages/validity_frame`.

Repository folders outside the package
--------------------------------------

.. code-block:: text

   HydroModPy/
   |-- docs/                  Sphinx documentation source (this site).
   |-- examples/              Runnable example projects (TOML + Python).
   |-- hydromodpy/            Python package (see layout above).
   |-- hydromodpy_annex/      Project-specific tools that depend on the
   |                          package but stay outside the core API.
   |-- install/               Conda environment files and WSL helpers.
   |-- tests/                 Five-tier test tree (unit, integration,
   |                          e2e, regression, validation).
   |-- tools/                 Doc-gallery, PlantUML setup, CI helpers.
   `-- validation_cases/      Reusable scientific benchmark inventory.

Dependency direction is one-way: ``hydromodpy_annex/`` and ``tools/``
may import the core package, but the package itself must not import
from them. The architecture matrix in :doc:`layered-architecture`
enforces the same rule between subpackages.

Solver binaries
---------------

MODFLOW, MODPATH, and MT3D-USGS executables are not shipped with the
wheel. They are downloaded on first use into a managed cache
(``~/.cache/hydromodpy/bin/`` by default) by
``hydromodpy.solver.modflow_common.binaries``. ``hmp install-binaries``
fetches them eagerly. See :doc:`/install` for the CLI flags.

See also
--------

- :doc:`layered-architecture` for the strict import rules between
  subpackages.
- :doc:`overview/code-reading-guide` for guided reading paths inside
  each package.
- :doc:`packages/index` for one focused page per subpackage.
