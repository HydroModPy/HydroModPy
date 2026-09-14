core
====

``hydromodpy.core`` is the kernel leaf. Every other layer may import
from it, and ``core`` itself must not import sibling layers.

Sub-modules
-----------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Module
     - Role
   * - ``core/auth/``
     - :class:`AuthBackend` Protocol plus the bundled
       :class:`LocalAuthBackend` and :func:`get_auth_backend`
       selector. See the "Auth backend" section below.
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
     - Calendar and simulation time-window helpers reused by physics and
        solver layers. Neutral time-grid generation lives in
        ``discretization/time``.
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
- ``hydromodpy.core.metrics.{nse, kge, rmse, ...}``
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
5. ``hydromodpy/core/metrics.py`` for the metric
   contract.

Auth backend
------------

``core/auth/`` carries the actor-resolution abstraction shared by the
catalog audit trail and the privacy purge worker:

- ``core/auth/protocol.py`` defines :class:`AuthBackend`, a runtime
  ``Protocol`` with ``current_user()``, ``can_read(resource)`` and
  ``can_write(resource)``.
- ``core/auth/backends.py`` ships :class:`LocalAuthBackend`, the
  permissive default. It reads ``HMP_USER`` then ``USER`` /
  ``USERNAME`` then :func:`getpass.getuser`, and answers ``True`` to
  every ACL check.
- ``core/auth/selection.py`` exposes :func:`get_auth_backend`, which
  reads the ``HMP_AUTH_BACKEND`` env var (or its argument) to pick
  an implementation. Unknown names raise ``ValueError`` so misspelt
  deployment configs fail loudly.

Wiring: ``results/catalog/audit.py:_resolve_actor`` and
``cli/_workers/privacy.py:_purge_resolve_operator`` both centralise
actor resolution through :func:`get_auth_backend`. Auth lives in
``core``, so any layer may consume it; auth itself must not import
outside ``core``.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core`` only.
- Allowed sources: every other layer.
- Any new sibling edge is a regression unless the YAML is updated with
  an explicit rationale.

See also
--------

- :doc:`config` for the root that consumes the unit aliases and the
  ``Profile`` enum.
- :doc:`/architecture/layered-architecture` for the matrix that
  pins ``core`` as the kernel leaf.
- :doc:`/architecture/how-to/add-a-config-field` for the recipe
  that uses ``Profile`` and the unit aliases.
