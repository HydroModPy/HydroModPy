Oceanic Source: constant
========================

Use ``source = "constant"`` for controlled examples, inland tests that need a
neutral oceanic placeholder, or coastal sensitivity studies with a fixed stage.

Minimal example
---------------

.. code-block:: toml

   [[data.oceanic.sources]]
   source = "constant"
   value = 0.0

Operational checks
------------------

- State the vertical datum represented by ``value``.
- Keep the value in the same conceptual convention as the boundary condition
  that will consume it.
- Do not treat a constant source as an observation; it is a controlled input.
