Geology Source: brgm_50k
========================

Use ``source = "brgm_50k"`` when the available public 1:50,000 geology layer
is appropriate for the study scale and the project benefits from finer
geological detail.

Minimal example
---------------

.. code-block:: toml

   [[data.geology.sources]]
   source = "brgm_50k"
   extent = "study_area"

Operational checks
------------------

- Finer geology can introduce many small interfaces. Check mesh size and
  interface count before activating every boundary as a constraint.
- The legend should remain readable after clipping.
- Property-table coverage is more important at fine scale because missing
  categories can become spatially fragmented.

Expected figure
---------------

Use a map panel to inspect categories, then a mesh or property-transfer figure
to decide whether the detail is useful or too noisy for the model objective.
