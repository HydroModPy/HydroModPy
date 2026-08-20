ProjectState
============

:class:`hydromodpy.project.state.ProjectState` is the typed dataclass
that owns the runtime state of a :class:`hydromodpy.project.Project`.
Twenty-one private attributes formerly mutated directly on the
``Project`` instance now live in this container.

Why a dataclass
---------------

The runtime state of a project mixes immutable inputs (the resolved
configuration, the solver name), cached preprocessing results (the
geographic context, the mesh inputs), and live counters (the run
counter, the run history). Spreading these as dunder-attributes on
:class:`Project` made the surface noisy and resisted static typing.

Encapsulating them in :class:`ProjectState` gives mypy and pyright a
single typed view, removes the dunder sprawl, and clarifies that those
fields are state, not behaviour.

Transparent proxy
-----------------

:class:`Project` proxies reads and writes through ``__getattr__`` and
``__setattr__``. Existing call sites that touch the legacy names keep
working unchanged:

.. code-block:: python

   project._cfg         # reads project._state.cfg
   project._config_path # reads project._state.config_path
   project._run_history # reads project._state.run_history

The public read-only view of the config is ``project.config``.

The full mapping lives in
:data:`hydromodpy.project.state.PROJECT_ATTR_TO_STATE_FIELD`. Any name
not in the map falls back to the regular attribute machinery, so
``project._runner`` and ``project._catalog`` keep living directly on the
instance.

Fields
------

The dataclass uses ``slots=True`` and groups the runtime state by
concern:

- **Configuration**: ``config_path``, ``cfg``, ``solver``, ``time_grid``.
- **Display flags**: ``headless``, ``no_display``.
- **Mesh inputs**: ``mesh_section_data``, ``external_mesh_input``,
  ``mesh_constraints_mode``, ``spatial_support_registry``,
  ``requested_support_ids``, ``requested_domain_supports``.
- **Workflow runtime**: ``ctx`` (the
  :class:`~hydromodpy.core.state.run_state.WorkflowContext`), ``store``
  (the open :class:`~hydromodpy.results.catalog.Catalog`).
- **Bookkeeping**: ``project_name``, ``run_counter``, ``active_runs``,
  ``last_wall_seconds``, ``phase``, ``data_loaded``, ``run_history``.

See Also
--------

- :class:`hydromodpy.project.Project` -- public facade that proxies to
  :class:`ProjectState`.
- :mod:`hydromodpy.project.phases` -- model-phase functions that mutate
  the state in place.
