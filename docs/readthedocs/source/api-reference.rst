API Reference
=============

This page mirrors the ``hydromodpy`` package layout. Each bullet below links to
the dedicated API section where classes, functions, and modules are documented.

Module overview
---------------

- :doc:`hydromodpy.core.config <api/hydromodpy-config>` - Pydantic parameter contracts
  (:class:`~hydromodpy.core.config.hydromodpy_config.HydroModPyConfig`,
  :class:`~hydromodpy.core.workspace.config.WorkspaceConfig`,
  :class:`~hydromodpy.spatial.geographic.geographic_config.GeographicConfig`)
  with validated fields, type constraints, and cross-field rules.
- :doc:`hydromodpy.spatial.geographic <api/hydromodpy-geographic>` - catchment delineation,
  DEM-derived supports, geographic runtime payloads, and the compatibility
  ``Geographic`` facade used by existing orchestration code.
- :doc:`numerical engines and postprocess <api/hydromodpy-modeling>` - solver
  engines, transport helpers, and post-processing utilities grouped under the
  compatibility surface exposed by :mod:`hydromodpy.modeling`.
- :doc:`hydromodpy.display <api/hydromodpy-display>` - figure catalog, rendering
  contracts, and solver-agnostic display entry points.
- :doc:`hydromodpy.physics.hydrology.pyhelp <api/hydromodpy-pyhelp>` - coupling layer with the HELP
  land-surface model, NetCDF conversion tools, rainfall-runoff post-processing,
  and CLI entry points.
- :doc:`hydromodpy.core.tools <api/hydromodpy-tools>` - shared toolbox for filesystem
  helpers, raster reprojection, geomorphology metrics, ERA5 ingestion, and plot
  presets.

Key entry points
----------------

- :class:`hydromodpy.core.config.HydroModPyConfig` - top-level Pydantic config loaded
  from a TOML file.
- :class:`hydromodpy.spatial.geographic.Geographic` - geographic compatibility
  facade that exposes the watershed-preprocessing outputs consumed by existing
  runtimes.

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


