Hydrographic Network UML Diagrams
=================================

Scope
-----

These diagrams document the software architecture around the hydrographic
network concept introduced to unify:

- the loaded reference network from ``data.hydrography``,
- the DEM-derived generated network from ``geographic.river_network``,
- the persisted run features used later by display and comparison layers.

They focus on responsibilities, runtime handoffs, and the difference between
canonical concepts and legacy-compatible technical bundles.

Code map
--------

- ``hydromodpy/spatial/geographic/core/hydrographic_network.py``:
  canonical network classes and naming contract.
- ``hydromodpy/spatial/geographic/core/hydrographic_network_comparison.py``:
  comparison result and geometric metrics.
- ``hydromodpy/spatial/geographic/core/river_network.py``:
  DEM-derived preprocessing outputs (`RiverNetworkProducts`).
- ``hydromodpy/spatial/geographic/core/derived_features.py``:
  geographic bundle that carries canonical network roles.
- ``hydromodpy/workflow/steps/result_ingestion.py`` and
  ``hydromodpy/spatial/geographic/store_ingestion.py``:
  persistence into the catalog.
- ``hydromodpy/results/run.py``:
  read facade and comparison accessors.
- ``hydromodpy/display/figures/hydrographic_network*.py``:
  standalone and comparison figures.
- ``hydromodpy/results/views.py`` and
  ``hydromodpy/display/figures/simulated_active_network.py``:
  computed simulated-active masks, metrics, and cell-map figure.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/geographic/core/hydrographic_network.py``
2. ``hydromodpy/spatial/geographic/core/river_network.py``
3. ``hydromodpy/spatial/geographic/core/derived_features.py``
4. ``hydromodpy/workflow/steps/result_ingestion.py`` and
   ``hydromodpy/spatial/geographic/store_ingestion.py``
5. ``hydromodpy/results/run.py``
6. ``hydromodpy/display/figures/hydrographic_network.py`` and
   ``hydromodpy/display/figures/hydrographic_network_comparison.py``

Class Diagram
-------------

Use this diagram when the main question is:
"which class is canonical, which one is technical, and which one is only a
comparison result?"

.. uml:: diagrams/hydrographic_network_class_map.wsd

.. literalinclude:: diagrams/hydrographic_network_class_map.wsd
   :language: text
   :caption: PlantUML (.wsd) source - hydrographic-network class responsibilities

Runtime Component Diagram
-------------------------

Use this diagram when the main question is:
"where does the network come from, how is it persisted, and who consumes it?"

.. uml:: diagrams/hydrographic_network_runtime_components.wsd

.. literalinclude:: diagrams/hydrographic_network_runtime_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - hydrographic-network runtime component diagram

End-to-End Sequence Diagram
---------------------------

Use this diagram when the main question is:
"what is the order of operations from loading/generation to comparison?"

.. uml:: diagrams/hydrographic_network_runtime_sequence.wsd

.. literalinclude:: diagrams/hydrographic_network_runtime_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - hydrographic-network runtime sequence diagram

Simulated-Active Pipeline Diagram
---------------------------------

Use this diagram when the main question is:
"how do simulated flux fields become a computed active-network view, and what
is still missing before a stored vector role exists?"

.. uml:: diagrams/hydrographic_network_simulated_active_pipeline.wsd

.. literalinclude:: diagrams/hydrographic_network_simulated_active_pipeline.wsd
   :language: text
   :caption: PlantUML (.wsd) source - simulated-active network pipeline

Availability Activity Diagram
-----------------------------

Use this diagram when the main question is:
"what happens when only one role exists, or when neither role exists?"

.. uml:: diagrams/hydrographic_network_availability_activity.wsd

.. literalinclude:: diagrams/hydrographic_network_availability_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - hydrographic-network availability activity diagram

Persistence And Run API Sequence Diagram
----------------------------------------

Use this diagram when the main question is:
"how do the persisted features reach the ``Run`` API, and what errors should a
developer expect when a role is missing?"

.. uml:: diagrams/hydrographic_network_persistence_run_sequence.wsd

.. literalinclude:: diagrams/hydrographic_network_persistence_run_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - hydrographic-network persistence and Run API sequence diagram

Persistence And Run API Notes
-----------------------------

From a developer point of view, the most important operational split is:

- ``result_ingestion.py`` persists the loaded reference role when
  ``data.hydrography`` produced one usable vector network.
- ``store_ingestion.py`` persists the generated role when the geographic
  preprocessing produced one usable DEM-derived network.
- ``SimulationCatalog`` stores those features under canonical names, with the
  generated role also mirrored under the legacy alias ``river_network``.
- ``Run`` does not guess. It first exposes the stored roles through
  ``available_hydrographic_network_roles()`` and ``has_hydrographic_network(...)``,
  then only enables comparison if both roles are present.

This means the runtime contract is intentionally asymmetric:

- persistence is tolerant and simply skips missing roles,
- reading one missing role raises a clear ``KeyError``,
- comparing two roles when one is absent raises a clear ``ValueError``,
- figure availability follows the same rule through ``run.display_capabilities``.

Which UML Diagrams Are Worth Maintaining?
-----------------------------------------

For this topic, the highest-value diagrams are:

1. A class diagram for the distinction between ``HydrographicNetwork``,
   ``HydrographicNetworks``, ``HydrographicNetworkComparison``, and
   ``RiverNetworkProducts``.
2. A component diagram for the source -> canonical object -> persistence ->
   consumer chain.
3. A sequence diagram for the end-to-end runtime path, including the
   "missing role" branch.
4. An activity diagram for the availability branches and output gating.
5. A developer-facing sequence diagram for persistence and ``Run`` behavior.
6. A simulated-active pipeline diagram for the distinction between computed
   masks and a future persisted vector role.

These diagrams answer the most common maintenance questions:

- where should a new field live?
- where should a conversion happen?
- when should a role be present or absent?
- who is allowed to compare or display the networks?

Lower-value diagrams for this topic are:

- state-machine diagrams, because these objects do not have a rich internal
  lifecycle;
- deployment diagrams, because there is no interesting multi-node deployment
  question here;
- exhaustive inheritance diagrams, because the hydrographic-network stack is
  composition-oriented rather than inheritance-heavy.

If more detail is needed later, the next useful addition would be one small
package-level component diagram focused only on:

- ``result_ingestion.py``
- ``store_ingestion.py``
- ``Run``
- the display figure registry
- the comparison export orchestrator

Related reading
---------------

- :doc:`mental-model-and-design-choices`
- :doc:`hydrographic-network-simulated-active-inventory`
- :doc:`../../scientific/hydrology/simulated-active-network`
- :doc:`code-reading-guide`
- :doc:`../../getting_started/comparison-workflow`
