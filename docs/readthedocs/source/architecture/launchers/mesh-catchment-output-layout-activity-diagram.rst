Mesh Catchment Output Layout
============================

Scope
-----

This diagram documents how the dedicated launcher resolves final artifacts and
cleanup behavior.

It focuses on:

- the ``standard`` versus ``flat`` output layout split,
- optional figure generation,
- exchange-bundle export,
- cleanup of intermediate geographic artifacts,
- extra naming and manifest rules when batch mode is active.

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_output_layout_activity.wsd

.. literalinclude:: diagrams/mesh_catchment_output_layout_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment output layout activity

Notes
-----

- ``flat`` layout is a dedicated-launcher convenience. It writes the final mesh
  artifacts directly under ``workspace.project_root`` while the intermediate
  runtime workspace lives elsewhere and can be deleted afterwards.
- ``process_simulation`` keeps the standard workspace structure because the
  simulation workflow still needs its runtime folders.
- Batch mode adds per-outlet filename patterns and one manifest CSV, but it
  still reuses the same mono-catchment output-resolution rules.
