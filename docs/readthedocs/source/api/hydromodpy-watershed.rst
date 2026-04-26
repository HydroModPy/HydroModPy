:orphan:

hydromodpy.watershed
====================

The historical ``hydromodpy.watershed`` package no longer ships as a concrete
runtime package in this repository. The old watershed-oriented API has been
split across the modern geographic, spatial-field, and data-manager packages.

Modern replacements
-------------------

.. autosummary::
   :nosignatures:
   :toctree: generated/watershed

   ~hydromodpy.spatial.geographic.CatchmentDelineation
   ~hydromodpy.spatial.field.geology.GeologyField
   ~hydromodpy.data.variables.hydrometry.manager.HydrometryManager
   ~hydromodpy.data.variables.intermittency.manager.IntermittencyManager
   ~hydromodpy.data.variables.piezometry.manager.PiezometryManager
   ~hydromodpy.data.variables.oceanic.manager.OceanicManager

Migration map
-------------

- Historical watershed delineation and setup now live under
  ``hydromodpy.spatial.geographic``.
- Geology field construction now lives under ``hydromodpy.spatial.field``.
- Hydrometry, intermittency, piezometry, oceanic, and climatic forcings now
  live under ``hydromodpy.data.variables``.
- The historical ``hydromodpy.data.climatic.Climatic`` facade no longer
  exists. Modern forcing data now uses dedicated variable managers such as
  ``precipitation``, ``etp``, ``temperature``, ``wind``, ``humidity``,
  ``radiation``, ``soil_moisture``, ``recharge``, and ``runoff``.
