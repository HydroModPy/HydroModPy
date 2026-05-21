hmp.mesh
========

Run the standalone mesh launcher from a TOML file. For embedded mesh
steps inside a regular simulation, model them as
``[workflow] mode = "simulation"`` with a ``[[simulation.process]]``
block whose ``type`` is ``"mesh"``.

Signature
---------

.. code-block:: python

   hmp.mesh(toml_path) -> dict

Reference
---------

.. autofunction:: hydromodpy.mesh
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   summary = hmp.mesh("mesh_only.toml")

See Also
--------

- :func:`hydromodpy.run` -- generic workflow launcher.
- :mod:`hydromodpy.spatial` -- mesh and geometry utilities.
