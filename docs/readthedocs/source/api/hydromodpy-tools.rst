hydromodpy.core.tools
========================

Helper routines used across the notebooks for filesystem handling, raster
processing, and plotting presets.

Toolbox overview
----------------

.. autosummary::
   :nosignatures:
   :toctree: generated/tools

   ~hydromodpy.core.tools.filesystem.create_folder
   ~hydromodpy.core.tools.display.plot_params

I/O note
--------

Raster and CRS helpers now live under ``hydromodpy.core.io``. They are kept
out of this autosummary page because their import chain depends on the wider
runtime stack used by the documentation build.
