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
- ``cli/commands/`` -- one module per verb (see inventory below).
- ``cli/_workers/`` -- CLI application services for commands whose
  reusable Python surface is not part of ``hydromodpy._api``. Workers
  may assemble diagnostics, catalog listings and developer reports, but
  they must not become hidden scientific workflow implementations.
- ``cli/workflows.py`` -- workflow dispatcher used by ``hmp run`` to
  pick the right launcher from ``[workflow].mode``.

Verb inventory
--------------

Twenty-six verbs ship today.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Verb
     - Role
   * - ``init``
     - Scaffold a workspace (``data/`` with its input cache, and
       ``projects/``).
   * - ``new``
     - Create a new project inside a workspace.
   * - ``config``
     - Generate a TOML template, validate one, list modules, open
       the wizard.
   * - ``schema``
     - Export JSON Schema and the companion files for frontends.
   * - ``run``
     - Execute a workflow (``simulation`` / ``calibration`` /
       ``overview`` / ``comparison`` / ``testbed``).
   * - ``dev``
     - Developer-only verbs (``run-script``, schema diagnostics,
       etc.).
   * - ``catalog``
     - Query the workspace-level catalog.
   * - ``display``
     - Render registered figures for one persisted simulation.
   * - ``report``
     - Render the HTML report for a calibration session.
   * - ``list``
     - Browse projects or runs in a workspace.
   * - ``export``
     - Export geographic data or simulation results to external
       formats.
   * - ``test``
     - Run the unit, integration, regression, validation tiers.
   * - ``data``
     - Inspect or manage custom data artefacts.
   * - ``lock``
     - Manage the reproducibility lockfile.
   * - ``show``
     - Show metadata, metrics, parameters of a simulation.
   * - ``compare``
     - Compare two simulations by id, prefix, or name.
   * - ``add``
     - Import a portable ``.hmp`` archive and dematerialise inputs.
   * - ``import``
     - Import a portable ``.hmp`` package into a workspace.
   * - ``doctor``
     - Diagnose Python, dependencies, solver binaries, workspace.
   * - ``inspect``
     - Inspect metadata, mesh, status, files of a simulation.
   * - ``manage``
     - Open the local browser UI for catalog tables and cleanup.
   * - ``install-binaries``
     - Download the MODFLOW / MODPATH / MT3D-USGS binaries.
   * - ``rank``
     - Rank simulations for a project by one metric.
   * - ``delete``
     - Delete a simulation (catalog row plus Zarr / Parquet
       artefacts).
   * - ``workspace``
     - Inspect or initialise workspace paths and storage
       conventions.
   * - ``completion``
     - Emit shell completion scripts (bash / zsh / fish).

Verb contract
-------------

Each module under ``cli/commands/`` exposes:

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
5. One small verb such as ``cli/commands/show.py`` to see the
   thin-handler convention.

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
