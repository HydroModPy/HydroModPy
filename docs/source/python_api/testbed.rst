hmp.testbed
===========

Run a TOML-driven method testbed.

Signature
---------

.. code-block:: python

   hmp.testbed(toml_path) -> Any

Reference
---------

.. autofunction:: hydromodpy.testbed

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   result = hmp.testbed("testbed_methods.toml")

See Also
--------

- :func:`hydromodpy.run` -- generic workflow launcher.
- :mod:`hydromodpy.workflow` -- workflow dispatcher and launchers.
