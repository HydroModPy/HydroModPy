:title: hmp.index

hmp.index
=========

Open the machine-wide global index that federates registered workspaces.

Signature
---------

.. code-block:: python

   hmp.index(db_path=None, *, read_only=False) -> GlobalIndex

Reference
---------

.. autofunction:: hydromodpy.index

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   idx = hmp.index(read_only=True)
   workspaces = idx.list_workspaces()

See Also
--------

- :func:`hydromodpy.open` -- workspace catalog (per-workspace view).
- :func:`hydromodpy.open_catalog` -- V1 catalog facade.
- :mod:`hydromodpy.core.state.global_index` -- federation implementation.
