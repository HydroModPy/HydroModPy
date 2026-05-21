Object-oriented patterns
========================

HydroModPy ships two complementary surfaces:

- A **functional facade** -- top-level verbs under :mod:`hydromodpy._api`
  (``hmp.run``, ``hmp.overview``, ``hmp.compare``, ``hmp.mesh``,
  ``hmp.report``, ``hmp.open``, ``hmp.open_catalog``) that take a TOML path or
  a config object and return a result.
- An **object-oriented facade** -- :class:`hydromodpy.project.Project` for
  setup-once, run-many sessions plus accessor objects for the input cache,
  the run catalog and the persisted artefact store.

This chapter documents the object surface: how :class:`Project` is built,
how its state is encapsulated, how to navigate runs and data, and how the
catalog wrappers behave as context managers.

For the verb surface, see :doc:`/python_api/index`.

.. toctree::
   :maxdepth: 1
   :caption: Pages

   project
   state
   accessors
   catalog

See Also
--------

- :class:`hydromodpy.project.Project` -- public facade.
- :class:`hydromodpy.project.state.ProjectState` -- typed runtime container.
- :class:`hydromodpy.results.catalog.SimulationCatalog` -- workspace catalog.
