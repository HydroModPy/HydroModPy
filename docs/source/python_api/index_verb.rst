:title: hmp.index

hmp.index
=========

Open the machine-wide global index that federates registered projects.

One row of the index is one project root, the directory that owns an
index database. A workspace root holds none of its own, so registering
one expands it into the projects it contains.

Signature
---------

.. code-block:: python

   hmp.index(db_path=None, *, read_only=True) -> GlobalIndex

Reference
---------

.. autofunction:: hydromodpy.index
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   idx = hmp.index(read_only=True)
   projects = idx.list_projects()

Registering needs the writable handle:

.. code-block:: python

   with hmp.index(read_only=False) as idx:
       idx.register("~/hydromodpy", label="default")

See Also
--------

- :func:`hydromodpy.open` -- project catalog (single-project view).
- :mod:`hydromodpy.core.state.global_index` -- federation implementation.
