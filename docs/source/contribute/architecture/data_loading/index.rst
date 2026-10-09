Data loading architecture
=========================

The data layer is the orchestration boundary for data loading. Before solver work
begins it answers three questions:

- which data families are active for this run;
- which manager loads each family;
- which external providers or local inputs those managers depend on.

This logic is centralised under ``hydromodpy.data``, so the project facade and the
simulation runner do not repeat the activation rules or the provider-specific code.
``hydromodpy/data/README.md`` is the map of the package: the variables, the
subpackages, the import rules and where to add what.

Code map
--------

- ``hydromodpy/data/loading/config_schema.py``: typed validation of the ``[data]``
  sections (``DataManagersConfig``).
- ``hydromodpy/data/loading/planner.py`` and ``plan.py``: activation inference
  (``DataPlanner``) and the immutable ``DataLoadPlan``.
- ``hydromodpy/data/loading/_dispatch.py``: ``VARIABLE_SPECS``, the one list that maps a
  variable name to its config class and its manager.
- ``hydromodpy/data/loading/loader.py``: ``DataManagersRuntimeLoader``, the dispatcher
  used after planning.
- ``hydromodpy/core/state/data.py``: ``LoadedDataContext``, one field per variable,
  which the loader fills and the project facade and the structure binders read.
- ``hydromodpy/data/variables/*``: one package per variable, with its typed config,
  manager and I/O.

Recommended reading path: ``hydromodpy/data/README.md``, ``loading/config_schema.py``,
``loading/planner.py``, ``loading/loader.py``, then one package under
``hydromodpy/data/variables/``.

Responsibilities
----------------

``config_schema.py`` validates ``[data]`` and normalises its typed sections.
``planner.py`` merges the explicit types with the inference rules. ``plan.py`` stores
the immutable ``DataLoadPlan``. ``loader.py`` sends each activated type to its manager
and writes what it loaded into ``LoadedDataContext``. The facade stays focused on
execution order, and the data layer owns activation, validation and loading.

Activation and inference
------------------------

The activation contract is deterministic:

- an explicit ``data.types`` always wins, and the planner never infers over it;
- other types are inferred from the domain and flow configuration;
- the decision is stored in ``DataLoadPlan`` with one reason per inferred type.

The rules are in ``DataPlanner.build``. For example, a ``geology`` support in
``domain.supports`` activates ``geology``, a ``stream`` boundary condition activates
``hydrography``, an ``ocean`` one activates ``oceanic``, a lake or reservoir activates
the lake geometry, abacus, inflow and withdrawal families, and a soil reservoir
activates ``precipitation`` and ``etp``.

``data.inference_mode = "warn"`` accepts the inferences and records them.
``data.inference_mode = "strict"`` requires explicit typed sections for the inferred
families, except for the geology default.

Runtime dispatch
----------------

``DataManagersRuntimeLoader`` dispatches each activated type through ``VARIABLE_SPECS``.
A variable with a side effect of its own (``dem``, ``geology``, ``hydrography``) names a
dedicated loader method. The others go through the generic load path. Each family keeps
its own config and manager package, and the root layer only decides activation and calls
the right loader.

Providers
---------

Which provider serves which variable is in the data README (the table of variables, with
their sources) and in the generated catalog of data sources
(:doc:`/reference/data-sources`). Do not copy them into a page.

What a provider call needs
--------------------------

The architectural point is also what must be available for a call to succeed.
Typical constraints:

- SIM2-backed variables need a bounding box and a project time window;
- SHOM loading needs a resolved date range and one gauge selector: named station
  identifiers, or a mask whose centre the nearest gauge is found from;
- geology and DEM loading often rely on spatial masks or raster support;
- hydrography and watershed preprocessing depend on the Whitebox backend for some
  derived products;
- a local custom source is a first-class input and must not be silently overwritten by
  the cache.

The cache layer adds its own rules: an empty remote result may be cached as a sentinel to
avoid repeated failed calls, stored paths stay relative so a workspace is portable, and
``force_refresh`` bypasses the cache when a provider call must be repeated.

Definition and transfer
-----------------------

Classes
~~~~~~~

This static view documents the collaboration that defines which data
must be prepared, then transfers those data objects to the runtime
state where they are consumed.

It focuses on:

- data-type inference and normalization (``DataPlanner`` ->
  ``DataLoadPlan``);
- the loader that fills ``LoadedDataContext`` (``DataManagersRuntimeLoader``);
- the structural bindings that move loaded data to where it is consumed:
  geology into the ``Domain`` zones (``apply_geology_to_domain``), and oceanic levels,
  recharge, ETP, lakes, barriers and SFR networks into the ``Flow``
  (``apply_*_to_flow``).

.. uml:: diagrams/data_definition_transfer_class.wsd

Notes:

- ``DataLoadPlan`` defines **which** data families are active.
- ``DataManagersRuntimeLoader`` and the binders define **where** the
  corresponding objects are stored.
- Geology is transferred into ``Domain`` as a zone used by the process solvers.
- Hydrometry stays in the loaded-data state, for the calibration and the diagnostics.

Activity
~~~~~~~~

This control-flow view documents the activation of data families and
the transfer of concrete data objects to the right runtime holders.

It focuses on:

- planning-time activation (``DataPlanner.build``);
- the loading by ``DataManagersRuntimeLoader``;
- the structural bindings of geology, oceanic, recharge and the other loaded data;
- continuation into simulation execution after data placement is complete.

.. uml:: diagrams/data_definition_transfer_activity.wsd

Notes:

- The same raw TOML can influence both activation inference and data payloads.
- The plan is built by ``hydromodpy/project/phases.py`` and stored on the context. The
  loading and the bindings run in ``LoadDataStep`` (``hydromodpy/workflow/steps/data.py``).
- In ``data.inference_mode = "warn"`` an inferred family is accepted and recorded. In
  ``"strict"`` it needs an explicit section.

Adding to this layer
--------------------

A new family is :doc:`../how-to/add-a-data-variable`, a new provider for an existing family is
:doc:`../how-to/add-a-data-source`. The simulation-side consumer of the data layer is described in
:doc:`../simulation/toml-to-solver-walkthrough`.
