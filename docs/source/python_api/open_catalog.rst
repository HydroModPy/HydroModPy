hmp.open_catalog
================

Open the V1 catalog facade exposing the ``simulations``, ``inputs`` and
``projects`` namespaces. Usable as a context manager.

Signature
---------

.. code-block:: python

   hmp.open_catalog(workspace=None) -> CatalogFacade

Reference
---------

.. autofunction:: hydromodpy.open_catalog

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   with hmp.open_catalog("~/proj/naizin") as cat:
       sims = cat.simulations.find(solver="modflow6")

See Also
--------

- :func:`hydromodpy.open` -- workspace-level simulation catalog.
- :func:`hydromodpy.index` -- machine-wide global index of workspaces.
