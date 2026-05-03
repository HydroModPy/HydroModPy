API Reference
=============

This page mirrors the ``hydromodpy`` package layout. Each bullet below links to
the dedicated API section where classes, functions, and modules are documented.

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
- :doc:`numerical engines and postprocess <api/hydromodpy-modeling>` - solver
  engines (MODFLOW-NWT, MODFLOW 6, Boussinesq), transport helpers, and the
  postprocess surfaces under :mod:`hydromodpy.solver` and
  :mod:`hydromodpy.results`.
- :doc:`hydromodpy.display <api/hydromodpy-display>` - figure catalog, rendering
  contracts, and solver-agnostic display entry points.
- :doc:`hydromodpy.physics.hydrology.pyhelp <api/hydromodpy-pyhelp>` - coupling layer with the HELP
  land-surface model, NetCDF conversion tools, rainfall-runoff post-processing,
  and CLI entry points.
- :doc:`hydromodpy.tools (relocated) <api/hydromodpy-tools>` - filesystem helpers
  (``hydromodpy.core.io``) and plot presets (``hydromodpy.display.theme``).

Key entry points
----------------

- :func:`hydromodpy.open` - open a workspace and return a
  :class:`~hydromodpy.results.catalog.SimulationCatalog`.
- :func:`hydromodpy.run` - execute the same TOML workflow as ``hmp run`` from
  Python.
- :func:`hydromodpy.calibrate` - launch a calibration session from a TOML file.
- :func:`hydromodpy.compare` - compare two simulations by object or id.
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
   api/hydromodpy-modeling
   api/hydromodpy-display
   api/hydromodpy-pyhelp
   api/hydromodpy-tools
