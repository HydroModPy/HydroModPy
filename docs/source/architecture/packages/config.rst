config
======

``hydromodpy.config`` carries the root Pydantic model
``HydroModPyConfig`` that aggregates every TOML section. It is the
canonical configuration contract: anything a user can declare in a
project TOML must round-trip through this model.

Sub-modules
-----------

The ``config`` package is intentionally thin. Each section model
lives close to the package it configures (see :doc:`../how-to/add-a-config-field`
for the table). The composition root sits in
``hydromodpy/config/hydromodpy_config.py``.

Sections aggregated by ``HydroModPyConfig``
-------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - TOML section
     - Pydantic model
   * - ``[workflow]``
     - ``WorkflowConfig`` (selects ``simulation`` / ``calibration`` /
       ``overview`` / ``comparison`` / ``testbed``).
   * - ``[workspace]``
     - ``WorkspaceConfig`` (paths and four-branch resolver).
   * - ``[geographic]``
     - ``GeographicConfig`` (catchment and DEM init).
   * - ``[domain]``
     - ``DomainConfig`` (zones, depth model, supports).
   * - ``[data]``
     - ``DataManagersConfig`` (active variables and per-variable
       sources).
   * - ``[flow]``
     - ``FlowConfig`` (regime, parameters, IC / BC / sinks-sources).
   * - ``[transport]``
     - ``TransportConfig`` (per-solver parameter blocks).
   * - ``[simulation]``
     - ``SimulationConfig`` (time grid, ``[[process]]`` list).
   * - ``[solver]``
     - ``SolverConfig`` (active backend).
   * - ``[modflownwt]``
     - ``ModflowConfig`` (MODFLOW-NWT packages).
   * - ``[modflow6]``
     - ``Modflow6Config`` (MODFLOW 6 packages).
   * - ``[display]``
     - ``DisplayConfig`` (figure list and rendering toggles).
   * - ``[persistence]``
     - ``PersistenceConfig`` (DuckDB / Zarr / Parquet toggles and the
       lockfile).
   * - ``[analysis]``
     - ``AnalysisConfig`` (batch / comparison / capability gallery).
   * - ``[overview]``
     - ``OverviewConfig`` (no-solver workflow).
   * - ``[mesh_catchment]``
     - ``MeshCatchmentConfig`` (mesh-only workflow).
   * - ``[calibration]``
     - ``CalibrationConfig`` (parameters, method, objective,
       persistence).

Each model honours the project-wide invariants documented in
:doc:`../how-to/add-a-config-field`: ``ConfigDict(extra="forbid")``,
``Annotated`` fields with unit aliases and ``Profile`` annotation,
``Field`` with description and at least one example.

Key public symbols
------------------

- ``hydromodpy.config.HydroModPyConfig`` -- root model.
- ``HydroModPyConfig.from_toml(path)`` -- TOML loader; resolves
  relative paths against the file's directory and applies
  ``base_config`` chains.
- ``HydroModPyConfig.model_dump()`` -- canonical JSON dump used by
  ``hmp schema export``.

Recommended reading path
------------------------

1. ``hydromodpy/config/hydromodpy_config.py`` to see the
   composition root and the ``base_config`` chain.
2. ``hydromodpy/core/config_kit/introspect.py`` to understand how
   the ``Profile`` filter walks the model tree.
3. One section model (for example
   ``hydromodpy/physics/flow/flow_config.py``) to see the per-field
   conventions in practice.
4. ``hydromodpy/schema/export.py`` to see what is exported to
   frontends.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, plus every
  layer it composes (``physics``, ``data``, ``spatial``,
  ``simulation``, ``solver``, ``calibration``, ``results``,
  ``display``, ``analysis``, ``workflow``).
- Allowed sources: ``schema``, ``results``, ``workflow``, ``cli``,
  and the top-level facade.

The composition root is the only place where the cross-package
section types are imported together. Everywhere else, layers refer
to **their own** section model, not to the root.

See also
--------

- :doc:`/user_guide/config_reference/index` -- user-facing TOML
  reference (auto-generated from the same models).
- :doc:`/architecture/how-to/add-a-config-field` -- step-by-step
  recipe.
- :doc:`schema` -- JSON Schema export and partial-field validator
  built on top of these models.
