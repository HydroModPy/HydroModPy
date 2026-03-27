StructuredGrid Build Sequence Diagram
=====================================

Scope
-----

This diagram documents the dynamic workflow that turns one user-facing SGrid
config payload into one FloPy ``StructuredGrid``.

It highlights:

- validation and normalization of ``SGridConfig``,
- top-surface loading and planar discretization,
- the different branches used to resolve the bottom surface,
- the final handoff to ``StructuredGridBuilder`` for grid assembly.

Reading Guide
-------------

- ``->`` means a call.
- ``-->`` means a returned value.
- ``alt`` blocks show the mutually exclusive bottom-surface strategies driven
  by ``cfg.genmtd_bot``.

Diagram source
--------------

.. uml:: diagrams/structured_grid_build_sequence.wsd

.. literalinclude:: diagrams/structured_grid_build_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - StructuredGrid build sequence diagram

Notes
-----

- ``build_sgrid_from_config(...)`` owns config resolution and surface
  preparation.
- ``StructuredGridBuilder`` stays narrower: it validates top/bottom geometric
  consistency, computes vertical layering, and instantiates the FloPy grid.
- For the static class relationships around the resulting grid, see
  :doc:`structured-grid-class-diagram`.
