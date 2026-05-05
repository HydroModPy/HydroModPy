DEM Source: ign_bdalti
======================

Use ``source = "ign_bdalti"`` when the project should retrieve public IGN BD
ALTI elevation data from the configured spatial support.

Minimal example
---------------

.. code-block:: toml

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"

Operational checks
------------------

- ``extent`` should match the support needed by the workflow:
  ``watershed`` for basin runs, ``study_area`` for broader preprocessing.
- API-backed files should be visible in the workspace data cache when a
  workspace is active.
- Rebuild or refresh only when the configured extent or data policy changes.

Expected figure
---------------

The expected visual result is the same DEM support panel used by custom DEMs:
terrain, watershed boundary, and outlet context must be spatially coherent.
