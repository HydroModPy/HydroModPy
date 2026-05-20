catalog
=======

``hydromodpy.catalog`` is the V1 facade over the three DuckDB scopes
(per-workspace cache, per-project catalog, machine-wide index). It is
the canonical entry point for :func:`hmp.open_catalog` and sits above
``results`` and ``data`` without the reverse edge.

Sub-modules
-----------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Module
     - Role
   * - ``catalog/facade.py``
     - :class:`CatalogFacade` and :func:`open_catalog`. Resolves the
       workspace, builds the three namespaces, and exposes a context
       manager that closes underlying DuckDB handles.
   * - ``catalog/simulations.py``
     - :class:`SimulationsNamespace`. Read-mostly access to the
       project catalog rows (``find``, ``get``, ``latest``).
   * - ``catalog/inputs.py``
     - :class:`InputsNamespace`. Lookup over the per-workspace data
       cache (``list``, ``get`` by variable).
   * - ``catalog/projects.py``
     - :class:`ProjectsNamespace`. Lookup over the machine-wide
       index of registered projects.

Mutators (since v1.x.6)
-----------------------

The catalog write surface lives on
:class:`hydromodpy.results.catalog.writes_duckdb.WritesMixinDuckDB`
(consumed by the project-scope :class:`SimulationCatalog`). Four
mutators ship with T6.B, each audited and wrapped in
``with_lock_retry`` so concurrent CLI calls serialise cleanly:

- ``rename_simulation(sim_id, new_name)`` -- rename a simulation row
  in place; raises ``DuplicateSimulationNameError`` on
  ``(project, name)`` collision.
- ``remove_tag(sim_id, tag)`` -- drop a single ``(sim_id, tag)`` row;
  returns ``True`` when a row was removed.
- ``update_parameter(sim_id, param_name, value, *, zone_id=None, unit=None, parameterization=None)``
  -- update an existing parameter row; raises ``KeyError`` when the
  ``(sim_id, param_name, zone_id)`` tuple is absent.
- ``remove_tracked_file(sim_id, role, canonical_path)`` -- drop one
  row from ``tracked_files``; returns ``True`` on match.

Every mutator early-returns when ``PersistenceConfig.save_catalog``
is False, so a single switch governs the DuckDB sink.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``data``, ``results``,
  ``catalog``.
- Allowed sources: ``project``, ``cli``. The reverse edge from
  ``data`` or ``results`` into ``catalog`` is forbidden so the
  facade stays a one-way wrapper.

See also
--------

- :doc:`results` for the project catalog and ``Run`` facade reached
  through this facade.
- :doc:`/python_api/open_catalog` for the public Python entry point.
- :doc:`/architecture/storage-layout` for the DuckDB file layout.
