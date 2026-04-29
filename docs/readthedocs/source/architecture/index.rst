Architecture & Code Reading
===========================

This section is the main entry point for HydroModPy technical
documentation. It groups both design-level diagrams and code-oriented
reading guides for the main HydroModPy modules.

Use this tab when you want:

- module and package boundaries,
- class, component, activity, and sequence diagrams,
- runtime orchestration and handoff views,
- software-facing design notes separated from scientific method notes,
- guided entry points for reading the codebase package by package.

For equations, modelling assumptions, and method documentation, see
:doc:`../scientific/index`.

Package layout
--------------

The Python package lives under ``hydromodpy/``. Each subpackage has one
clear responsibility. The list below summarizes what each folder
contains. Open the full reading guide in
:doc:`overview/code-reading-guide` once you know which module you want
to study.

.. code-block:: text

   hydromodpy/
   |-- cli/           Command-line entry point (hmp, hydromodpy aliases)
   |-- analysis/       Comparison, batch, and capability gallery helpers
   |-- calibration/    Optuna engine, objectives, optimizers, evaluators
   |-- core/           Config contracts, workspace anchoring, registry
   |-- data/           Data managers (BRGM, BD TOPAGE, Hub'Eau, SIM2, ...)
   |-- display/        Solver-agnostic figures and figure catalog
   |-- physics/        Process definitions (Flow, Transport, BCs, ICs)
   |-- pipeline/       Pipeline runner with checkpointing on DuckDB
   |-- results/        Result catalog (DuckDB ledger + Zarr fields)
   |-- schema/         JSON Schema export for frontend integrations
   |-- simulation/     Run orchestration (planner, registry, context)
   |-- solver/         Solver abstraction + MODFLOW-NWT/MF6/Boussinesq
   |-- spatial/        Catchment delineation, DEM, mesh, field maps
   `-- workflow/       Composable workflow steps and run state

Top-level helpers in ``hydromodpy/``:

- ``project.py`` is the public ``Project`` facade that wires the pipeline
  end to end. Most user code only imports from here.
- ``__init__.py`` re-exports the stable API surface (``Project``,
  ``Config``, ``Geographic``, ``Domain``, ``Flow``, ``Sim``, etc.) and
  bootstraps the PROJ database on import.

Repository folders outside the package:

.. code-block:: text

   HydroModPy/
   |-- docs/readthedocs/      Sphinx documentation source (this site)
   |-- examples/              Runnable example projects (TOML + Python)
   |-- hydromodpy/            Python package (see layout above)
   |-- hydromodpy_annex/      Project-specific tools that depend on the
                              package but are not part of the core API
   |-- install/               Conda environment files and WSL helpers
   |-- tests/                 Unit, regression, and validation tiers
   |-- tools/                 Doc gallery, PlantUML setup, CI helpers
   `-- validation_cases/      Analytical and numerical reference cases

MODFLOW, MODPATH, and MT3D-USGS binaries are no longer shipped with the
repository. They are downloaded on first use into a managed cache
(``~/.cache/hydromodpy/bin/`` by default) by
``hydromodpy.solver.modflow_common.binaries``. See :doc:`../install`
for the ``hmp install-binaries`` command.

The dependency direction is one-way: ``hydromodpy_annex`` and tooling
under ``tools/`` may import the core package, but the package itself
must not import from them.

.. toctree::
   :maxdepth: 2

   overview/index
   data_loading/index
   spatial_support/index
   field/index
   mesh/index
   calibration/index
   process/index
   solver/index
   simulation/index
