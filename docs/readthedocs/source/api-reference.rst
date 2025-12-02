API Reference
=============

This page mirrors the ``hydromodpy`` package layout. Each bullet below links to
the dedicated API section where classes, functions, and modules are documented.

Module overview
---------------

- :doc:`hydromodpy.watershed <api/hydromodpy-watershed>` – watershed extraction,
  basin descriptors (geography, geology, hydraulics, climate, hydrography, etc.),
  and the main :class:`hydromodpy.watershed_root.Watershed` object.
- :doc:`hydromodpy.modeling <api/hydromodpy-modeling>` – preprocessing /
  processing / post-processing helpers for MODFLOW, MODPATH, surface
  mass-transfer routing, MT3DMS transport, and time-series utilities.
- :doc:`hydromodpy.display <api/hydromodpy-display>` – visualisation routines
  for descriptors and simulation results plus VTU/VTK exporters.
- :doc:`hydromodpy.pyhelp <api/hydromodpy-pyhelp>` – coupling layer with the HELP
  land-surface model, NetCDF conversion tools, rainfall–runoff post-processing,
  and CLI entry points.
- :doc:`hydromodpy.tools <api/hydromodpy-tools>` – shared toolbox for filesystem
  helpers, raster reprojection, geomorphology metrics, ERA5 ingestion, and plot
  presets.

Key entry points
----------------

- :class:`hydromodpy.watershed_root.Watershed` – main object orchestrating every
  example (accessible via :mod:`hydromodpy.watershed_root`).

Detailed documentation
----------------------

.. toctree::
   :maxdepth: 2

   api/hydromodpy-watershed
   api/hydromodpy-modeling
   api/hydromodpy-display
   api/hydromodpy-pyhelp
   api/hydromodpy-tools
