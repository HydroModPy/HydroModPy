hmp.read
========

Read a variable from a simulation with auto-dispatch across Zarr fields,
DuckDB timeseries, and GeoParquet geographic features.

Signature
---------

.. code-block:: python

   hmp.read(sim, var, *, time=None, layer=None, sel=None, bbox=None, lazy=None) -> Any

Reference
---------

.. autofunction:: hydromodpy.read

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/hmp_workspace")
   run = catalog.latest()

   da = hmp.read(run, "head")                       # xr.DataArray, lazy
   arr = hmp.read(run, "head", time=-1, layer=0)    # np.ndarray, eager
   ts = hmp.read(run, "discharge", sel={"station": "outlet"})
   gdf = hmp.read(run, "watershed_polygon")         # geographic feature

See Also
--------

- :func:`hydromodpy.open` -- open the catalog that yields ``Run`` objects.
- :mod:`hydromodpy.results` -- catalog, run, and field registry.
