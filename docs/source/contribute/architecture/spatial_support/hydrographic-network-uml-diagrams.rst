Hydrographic network diagrams
=============================

Scope
-----

These diagrams document the software architecture around the hydrographic
network concept introduced to unify:

- the loaded reference network from ``data.hydrography``,
- the DEM-derived generated network from ``geographic.river_network``,
- the persisted run features used later by display and comparison layers.

They focus on responsibilities, runtime handoffs, and the difference between
canonical concepts and technical preprocessing bundles.

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
- ``hydromodpy/workflow/steps/prepare_solver/`` and
  ``hydromodpy/spatial/geographic/store_ingestion.py``:
  persistence into the catalog.
- ``hydromodpy/results/run/view.py``:
  read facade and comparison accessors.
- ``hydromodpy/display/figures/hydrographic_network*.py``:
  standalone and comparison figures.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/geographic/core/hydrographic_network.py``
2. ``hydromodpy/spatial/geographic/core/river_network.py``
3. ``hydromodpy/spatial/geographic/core/derived_features.py``
4. ``hydromodpy/workflow/steps/prepare_solver/`` and
   ``hydromodpy/spatial/geographic/store_ingestion.py``
5. ``hydromodpy/results/run/view.py``
6. ``hydromodpy/display/figures/hydrographic_network.py`` and
   ``hydromodpy/display/figures/hydrographic_network_comparison.py``

Classes
-------

Use this diagram when the main question is:
"which class is canonical, which one is technical, and which one is only a
comparison result?"

.. uml:: diagrams/hydrographic_network_class_map.wsd

Runtime components
------------------

Use this diagram when the main question is:
"where does the network come from, how is it persisted, and who consumes it?"

.. uml:: diagrams/hydrographic_network_runtime_components.wsd

End-to-end sequence
-------------------

Use this diagram when the main question is:
"what is the order of operations from loading/generation to comparison?"

.. uml:: diagrams/hydrographic_network_runtime_sequence.wsd

Availability
------------

Use this diagram when the main question is:
"what happens when only one role exists, or when neither role exists?"

.. uml:: diagrams/hydrographic_network_availability_activity.wsd

Persistence and the Run API
---------------------------

Use this diagram when the main question is:
"how do the persisted features reach the ``Run`` API, and what errors should a
developer expect when a role is missing?"

.. uml:: diagrams/hydrographic_network_persistence_run_sequence.wsd

Persistence and Run API notes
-----------------------------

From a developer point of view, the most important operational split is:

- The ``prepare_solver`` step (``hydromodpy/workflow/steps/prepare_solver/``) persists
  the loaded reference role when ``data.hydrography`` produced one usable vector network.
- ``store_ingestion.py`` persists the generated role when the geographic
  preprocessing produced one usable DEM-derived network.
- ``Catalog`` stores those features under canonical names only.
- ``Run`` does not guess. It first exposes the stored roles through
  ``available_hydrographic_network_roles()`` and ``has_hydrographic_network(...)``,
  then only enables comparison if both roles are present.

This means the runtime contract is intentionally asymmetric:

- persistence is tolerant and simply skips missing roles,
- reading one missing role raises a clear ``KeyError``,
- comparing two roles when one is absent raises a clear ``ValueError``,
- a figure that needs a role absent from the run says so through its
  ``unavailable_reason``.

Related reading
---------------

- :doc:`../mental-model`, which names the roles and the canonical file names.
- :doc:`../simulation/comparison-workflow` for the metrics a comparison writes.
