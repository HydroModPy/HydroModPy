cli
===

``hydromodpy.cli`` is the top-level dispatcher for the ``hmp`` and
``hydromodpy`` console entry points. One verb per module under
``cli/commands/``, registered through ``ALL_COMMANDS`` in
``cli/commands/__init__.py``.

Sub-modules
-----------

- ``cli/main.py`` -- argparse dispatcher; iterates ``ALL_COMMANDS``
  and forwards the parsed namespace to ``args._handler``.
- ``cli/commands/`` -- one module per leaf verb, one sub-package per
  verb family (see inventory below).
- ``cli/_conventions.py`` -- the shared argparse grammar
  (``workspace_parser``, ``confirm_parser``, ``format_parser``,
  ``profile_parser``, ``add_sim_ref``, ``add_action_subparsers``).
- ``cli/helpers.py`` -- typed exit codes and ``exit_code_for(exc)``.
- ``cli/_workers/`` -- CLI application services for commands whose
  reusable Python surface is not part of ``hydromodpy._api``. Workers
  may assemble diagnostics, catalog listings and developer reports, but
  they must not become hidden scientific workflow implementations.

The ``[workflow].mode`` dispatch does not live here: ``hmp run`` calls
``hydromodpy._api.run``, which reaches
``hydromodpy/project/dispatch/workflow.py``.

Verb inventory
--------------

Seventeen top-level verbs ship today, in ``ALL_COMMANDS`` order.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Verb
     - Role
   * - ``workspace``
     - Workspace lifecycle and global-index registration: ``init``,
       ``list``, ``register``, ``search``, ``forget``, ``prune``,
       ``clean``.
   * - ``project``
     - Projects inside a workspace: ``new``, ``list``, ``show``,
       ``delete``.
   * - ``catalog``
     - The run lifecycle: ``ls``, ``query``, ``show``, ``point``,
       ``gc``, ``reindex``, ``delete``, ``restore``, ``trash``,
       ``tag``, ``note``, ``rename``, ``diff``, ``watch``, ``export``,
       ``import``, ``rerun``.
   * - ``data``
     - Input cache and ``.hmp`` package exchange: ``ls``, ``get``,
       ``check``, ``add``, ``remove``, ``prune``, ``archive``,
       ``restore``, ``export``, ``export-package``, ``import``.
   * - ``viz``
     - Figures: ``list`` (registered names), ``show`` (one figure for
       one run), ``gallery`` (the ``[display]`` set for one or several
       runs).
   * - ``config``
     - ``template``, ``check``, ``schema``, ``wizard``.
   * - ``dev``
     - Developer-only: ``run-script``, ``completion``, ``schema``,
       ``lock``, ``rank``, ``manage``.
   * - ``audit``
     - ``list`` and ``verify`` on the hash-chained audit log.
   * - ``privacy``
     - ``purge`` a simulation with a JSON certificate, and ``verify``
       that certificate.
   * - ``run``
     - Execute a workflow (``simulation`` / ``calibration`` /
       ``overview`` / ``comparison`` / ``testbed``).
   * - ``calibrate``
     - Run a calibration workflow from a TOML config.
   * - ``spinup``
     - Cyclic spin-up until heads and lake stage converge.
   * - ``site-selection``
     - ``plan``, ``select-catchments``, ``build-observed``,
       ``build-generated``, ``report``.
   * - ``test``
     - Run the ``unit``, ``regression`` or ``validation`` tier.
   * - ``report``
     - ``render`` a calibration report, ``compare`` two runs, build a
       ``catchment`` report.
   * - ``doctor``
     - Diagnose Python, dependencies, solver binaries, workspace.
   * - ``install-binaries``
     - Download the MODFLOW / MODPATH / MT3D-USGS binaries.

Verb contract
-------------

Each leaf module under ``cli/commands/`` exposes:

.. code-block:: python

   NAME: str = "myverb"
   HELP: str = "One-line description."

   def register(subparsers) -> argparse.ArgumentParser:
       parser = subparsers.add_parser(NAME, help=HELP)
       ...
       parser.set_defaults(_handler=run)
       return parser

   def run(args: argparse.Namespace) -> None:
       ...

The dispatcher iterates ``ALL_COMMANDS``, calls ``register`` on
each, then forwards the parsed namespace to ``args._handler``.

A verb family (``workspace/``, ``project/``, ``catalog/``, ``data/``,
``viz/``, ``dev/``) is a sub-package: its ``__init__.py`` carries
``NAME``, ``HELP`` and an ``ACTIONS`` tuple, and every action module
repeats the same four symbols. The group is attached with
``add_action_subparsers``, so a bare ``hmp catalog`` is a usage error
and exits 2.

For V1, the CLI boundary is:

- ``cli/commands/*.py`` parse arguments, call ``hydromodpy._api`` or a
  named CLI worker, format output and map errors to exit codes.
- ``cli/_workers/*.py`` is an application layer for CLI-only features
  such as catalog browsing, audit display and developer diagnostics.
- Reusable user-facing workflows should live in ``hydromodpy._api`` or
  in their domain package, then be called by the command module.

Recommended reading path
------------------------

1. ``hydromodpy/cli/main.py`` for the dispatch loop.
2. ``hydromodpy/cli/commands/__init__.py`` to see the
   registered tuple ``ALL_COMMANDS``.
3. ``hydromodpy/cli/commands/run.py`` for the canonical workflow
   verb.
4. ``hydromodpy/project/dispatch/workflow.py`` for the
   ``[workflow].mode`` -> launcher dispatch.
5. One small verb such as ``cli/commands/catalog/point.py`` to see the
   thin-handler convention: parse, call a worker, format, map errors to
   exit codes.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``<root>``, every stable production layer,
  ``catalog``, ``project`` and ``cli``. ``validity_frame`` is not part
  of the stable CLI target set.
- Allowed sources: none; ``cli`` is a leaf consumer.

See also
--------

- :doc:`/user_guide/cli-reference` -- user-facing CLI inventory with
  every flag.
- :doc:`/architecture/how-to/add-a-cli-command` -- step-by-step
  recipe.
- :doc:`/getting_started/cli-quickstart` -- first-run path.
