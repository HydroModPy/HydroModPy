Tools API
=========

Helper routines previously gathered under ``hydromodpy.core.tools`` now live
in their canonical homes:

.. autosummary::
   :nosignatures:
   :toctree: generated/tools

   ~hydromodpy.core.io.filesystem.create_folder
   ~hydromodpy.display.theme.plot_params

I/O note
--------

Raster and CRS helpers live under ``hydromodpy.core.io``. They are kept
out of this autosummary page because their import chain depends on the wider
runtime stack used by the documentation build.
