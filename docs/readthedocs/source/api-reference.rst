API Reference
=============

This page mirrors the ``hydromodpy`` package layout. Each bullet below links to
the dedicated API section where classes, functions, and modules are documented.

Module overview
---------------

- :doc:`hydromodpy.config <api/hydromodpy-config>` - Pydantic parameter contracts
  (:class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig`,
  :class:`~hydromodpy.simulation.workspace.config.WorkspaceConfig`,
  :class:`~hydromodpy.geographic.geographic_config.GeographicConfig`)
  with validated fields, type constraints, and cross-field rules.
- :doc:`hydromodpy.legacy.watershed <api/hydromodpy-watershed>` - watershed extraction,
  basin descriptors (geography, geology, hydraulics, hydrography) plus
  data-manager entry points used by :class:`hydromodpy.legacy.watershed.watershed_root_legacy.Watershed`.
- :doc:`hydromodpy.modeling <api/hydromodpy-modeling>` - preprocessing /
  processing / post-processing helpers for MODFLOW, MODPATH, surface
  mass-transfer routing, MT3DMS transport, and time-series utilities.
- :doc:`hydromodpy.display <api/hydromodpy-display>` - visualisation routines
  for descriptors and simulation results plus VTU/VTK exporters.
- :doc:`hydromodpy.hydrology.pyhelp <api/hydromodpy-pyhelp>` - coupling layer with the HELP
  land-surface model, NetCDF conversion tools, rainfall-runoff post-processing,
  and CLI entry points.
- :doc:`hydromodpy.support.tools <api/hydromodpy-tools>` - shared toolbox for filesystem
  helpers, raster reprojection, geomorphology metrics, ERA5 ingestion, and plot
  presets.

Key entry points
----------------

- :class:`hydromodpy.legacy.watershed.watershed_root_legacy.Watershed` - main object orchestrating every
  example (accessible via :mod:`hydromodpy.legacy.watershed.watershed_root_legacy`).
- :class:`hydromodpy.config.HydroModPyConfig` - top-level Pydantic config loaded
  from a TOML file.

Detailed documentation
----------------------

.. toctree::
   :maxdepth: 2

   api/hydromodpy-config
   api/hydromodpy-watershed
   api/hydromodpy-modeling
   api/hydromodpy-display
   api/hydromodpy-pyhelp
   api/hydromodpy-tools


