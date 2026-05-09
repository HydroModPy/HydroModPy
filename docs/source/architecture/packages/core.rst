core
====

``hydromodpy.core`` is the kernel leaf. Every other layer may import
from it; ``core`` itself imports nothing from sibling layers. This is
the shared vocabulary of units, profiles, metrics, I/O helpers,
runtime state, and input-file tracking.

Sub-modules
-----------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Module
     - Role
   * - ``core/config_kit/``
     - ``Profile`` enum (USER / DEV / EXPERT), introspection helpers,
       persistence-config base, and shared field-introspection
       utilities used by the TOML template and the JSON Schema.
   * - ``core/contracts/``
     - Lightweight contract types reused across layers.
   * - ``core/io/``
     - ``json_dumps`` / ``json_loads`` (deterministic),
       ``HTTPClient`` (retry / backoff / timeout / SHA-256), raster
       and vector I/O wrappers, CRS helpers, PROJ bootstrap, signed
       pickle, DB retry decorator.
   * - ``core/logging/``
     - ``LogManager`` configured at package import; verbose / quiet
       toggles for the CLI.
   * - ``core/metrics/``
     - Canonical goodness-of-fit metrics: ``align``, ``nse``,
       ``log_nse``, ``kge``, ``rmse``, ``mae``, ``bias``, ``pbias``,
       ``correlation``. Pure NumPy, JSON-roundtrip floats.
   * - ``core/rng/``
     - Reproducible random-number wrappers.
   * - ``core/state/``
     - Runtime registries shared by launcher and execution:
       ``ExecutionRegistry``, ``WorkflowContext``,
       ``LoadedDataContext``, ``SetupContext``. Generic types so the
       kernel does not depend on sibling layers.
   * - ``core/time/``
     - Calendar and timestep helpers reused by physics and solver
       layers.
   * - ``core/toml_io/``
     - TOML readers and writers used by ``HydroModPyConfig.from_toml``.
   * - ``core/tracking/``
     - ``InputFile`` annotation, ``TrackedFileEntry``,
       ``collect_input_files`` walker. Powers the reproducibility
       manifest.
   * - ``core/units/``
     - ``Annotated`` aliases backed by pydantic-pint:
       ``Length``, ``Area``, ``Volume``, ``Time``, ``FlowRate``,
       ``Velocity``, ``HydraulicConductivity``,
       ``SpecificStorage``, ``SpecificYield``, ``Dimensionless``.
       Bare numbers are interpreted in canonical SI; strings such as
       ``"0.36 m/h"`` auto-convert.
   * - ``core/workspace/``
     - ``WorkspaceConfig`` Pydantic model, ``Workspace`` runtime
       object, four-branch resolver (explicit, env var, scaffold,
       project).

Key public symbols
------------------

Often imported by other layers:

- ``hydromodpy.core.config_kit.profile.Profile`` -- visibility enum.
- ``hydromodpy.core.units.{Length, Time, FlowRate, ...}`` -- unit
  aliases.
- ``hydromodpy.core.workspace.workspace.Workspace`` -- workspace
  facade.
- ``hydromodpy.core.metrics.goodness_of_fit.{nse, kge, rmse, ...}``
  -- canonical metrics.
- ``hydromodpy.core.io.{json_dumps, json_loads, HTTPClient}`` --
  deterministic JSON, HTTP client.
- ``hydromodpy.core.tracking.input_file.InputFile`` -- file-tracking
  annotation.
- ``hydromodpy.core.state.{WorkflowContext, ExecutionRegistry}`` --
  runtime registries.
- ``hydromodpy.core.logging.LogManager`` -- shared logger.

Recommended reading path
------------------------

1. ``hydromodpy/core/units/types.py`` to learn the unit aliases used
   everywhere in Pydantic models.
2. ``hydromodpy/core/config_kit/profile.py`` and
   ``introspect.py`` to understand the visibility model.
3. ``hydromodpy/core/workspace/{config.py, resolve.py, workspace.py}``
   for the four-branch resolution.
4. ``hydromodpy/core/state/__init__.py`` for the cross-layer
   contexts.
5. ``hydromodpy/core/metrics/goodness_of_fit.py`` for the metric
   contract.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core`` only. The kernel never imports a sibling
  layer.
- Allowed sources: every other layer.
- No tolerated tolerance points at ``core``: any new edge into a
  sibling layer is a regression.

See also
--------

- :doc:`config` for the root that consumes the unit aliases and the
  ``Profile`` enum.
- :doc:`/architecture/layered-architecture` for the matrix that
  pins ``core`` as the kernel leaf.
- :doc:`/architecture/how-to/add-a-config-field` for the recipe
  that uses ``Profile`` and the unit aliases.
