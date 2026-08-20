catalog
=======

``hydromodpy.catalog`` is the read-only view over the per-workspace
input cache (``<workspace>/data/cache.duckdb``). It sits above
``results`` and ``data`` without the reverse edge.

The two other DuckDB scopes are reached elsewhere: the project catalog
through :func:`hmp.open`, which returns
``hydromodpy.results.catalog.Catalog``, and the machine-wide index
through :func:`hmp.index`, which returns
``hydromodpy.core.state.global_index.GlobalIndex``.

Sub-modules
-----------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Module
     - Role
   * - ``catalog/inputs.py``
     - :class:`InputsNamespace`, the only public symbol of the package.
       Lookup over the per-workspace data cache (``list``, ``get`` by
       variable). Reached via ``hydromodpy.catalog.InputsNamespace(ws)``
       or the ``hmp data`` CLI, not via :func:`hmp.open`.

Mutators (since v1.x.6)
-----------------------

The catalog write surface lives on
:class:`hydromodpy.results.catalog.writes_duckdb.WritesMixinDuckDB`
(consumed by the project-scope :class:`Catalog`). Four
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
- :doc:`/python_api/open` for the public Python entry point.
- :doc:`/architecture/storage-layout` for the DuckDB file layout.
