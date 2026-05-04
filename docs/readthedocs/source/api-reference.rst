API Reference
=============

This page documents the stable public surfaces exposed by ``hydromodpy``. The
package contains more implementation modules than are listed here; the API
reference is organized by user-facing role rather than by every internal file.

Module overview
---------------

- :doc:`hydromodpy.config <api/hydromodpy-config>` - Pydantic parameter contracts
  (:class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig`,
  :class:`~hydromodpy.core.workspace.config.WorkspaceConfig`,
  :class:`~hydromodpy.spatial.geographic.geographic_config.GeographicConfig`)
  with validated fields, type constraints, and cross-field rules.
- :doc:`hydromodpy.spatial.geographic <api/hydromodpy-geographic>` - catchment
  delineation, DEM-derived supports, and the geographic runtime payloads
  consumed by the simulation pipeline.
- :doc:`project, run, and catalog API <api/hydromodpy-project-results>` -
  programmatic entry points for opening a workspace, launching a project,
  browsing runs, querying fields, and exporting persisted results.
- :doc:`hydromodpy.data <api/hydromodpy-data>` - data-manager facade, loading
  plans, variable configuration objects, and provider-specific source blocks.
- :doc:`numerical engines and postprocess <api/hydromodpy-modeling>` - solver
  engines (MODFLOW-NWT, MODFLOW 6, Boussinesq), transport helpers, and the
  postprocess surfaces under :mod:`hydromodpy.solver` and
  :mod:`hydromodpy.results`.
- :doc:`simulation, workflow, and pipeline <api/hydromodpy-workflow-pipeline>` -
  simulation planning objects, workflow context, explicit pipeline steps,
  checkpointing, and resume support.
- :doc:`analysis and calibration <api/hydromodpy-analysis-calibration>` -
  comparison launchers, batch/testbed analysis surfaces, calibration engine,
  objectives, optimizers, reports, and parameter discovery helpers.
- :doc:`hydromodpy.display <api/hydromodpy-display>` - figure catalog, rendering
  contracts, and solver-agnostic display entry points.
- :doc:`hydromodpy.schema <api/hydromodpy-schema>` - JSON Schema export and
  partial field validation hooks used by external user interfaces.
- :doc:`hydromodpy.physics.hydrology.pyhelp <api/hydromodpy-pyhelp>` - coupling layer with the HELP
  land-surface model, NetCDF conversion tools, rainfall-runoff post-processing,
  and CLI entry points.
- :doc:`hydromodpy.core.tools <api/hydromodpy-tools>` - shared toolbox for filesystem
  helpers, raster reprojection, geomorphology metrics, ERA5 ingestion, and plot
  presets.

Key entry points
----------------

- :func:`hydromodpy.open` - open a workspace and return a
  :class:`~hydromodpy.results.catalog.SimulationCatalog`.
- :func:`hydromodpy.run` - execute the same TOML workflow as ``hmp run`` from
  Python.
- :func:`hydromodpy.calibrate` - launch a calibration session from a TOML file.
- :func:`hydromodpy.compare_pair` - compare two simulations by object or id.
- :func:`hydromodpy.doctor` - return a lightweight environment diagnostic.
- :class:`hydromodpy.project.Project` - Python facade for workspace setup,
  data loading, mesh construction, simulation, calibration, batch, comparison,
  and cleanup.
- :class:`hydromodpy.results.run.Run` - one persisted simulation run.
- :class:`hydromodpy.results.catalog.SimulationCatalog` - workspace-level run
  registry and result-query surface.
- :class:`hydromodpy.config.HydroModPyConfig` - top-level Pydantic config
  loaded from a TOML file.
- :class:`hydromodpy.spatial.geographic.CatchmentDelineation` - catchment
  delineation runtime, exposed by the geographic preprocessing pipeline.

Detailed documentation
----------------------

.. toctree::
   :maxdepth: 2

   api/hydromodpy-config
   api/hydromodpy-geographic
   api/hydromodpy-project-results
   api/hydromodpy-data
   api/hydromodpy-modeling
   api/hydromodpy-workflow-pipeline
   api/hydromodpy-analysis-calibration
   api/hydromodpy-display
   api/hydromodpy-schema
   api/hydromodpy-pyhelp
   api/hydromodpy-tools
