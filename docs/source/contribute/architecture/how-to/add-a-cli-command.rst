Add a CLI command
=================

The ``hmp`` and ``hydromodpy`` commands share the dispatcher in
``hydromodpy/cli/main.py``. A verb is one module under ``hydromodpy/cli/commands/``,
and the tuple ``ALL_COMMANDS`` in ``hydromodpy/cli/commands/__init__.py`` is the
inventory. The verbs and their flags are rendered in :doc:`/reference/cli/index`, so
this page does not list them.

Contract
--------

A command module exposes ``NAME``, ``HELP``, ``register(subparsers)`` and ``run(args)``.
``register`` adds the parser and sets ``_handler=run``. ``run`` parses nothing new, calls
one verb of ``hydromodpy.project.api``, formats the result and lets errors propagate.
Business logic never lives in the CLI layer, so a unit test can reach it without a
subprocess.

``hmp stop`` is the shortest complete example.

.. literalinclude:: /../../hydromodpy/cli/commands/stop.py
   :pyobject: register

.. literalinclude:: /../../hydromodpy/cli/commands/stop.py
   :pyobject: run

The shared flags come from ``hydromodpy/cli/conventions.py``. Use ``workspace_parser()``
for ``-w``, ``format_parser()`` for ``--format``, ``confirm_parser()`` for ``-y``,
``dry_run_parser()`` for ``--dry-run``, ``add_destination()`` for ``--to`` and
``add_sim_ref()`` for the ``sim_ref`` positional. ``tests/unit/cli/test_machine_output.py``
walks the argparse tree and fails on a verb without ``-w`` or ``--format``, or with a flag
that left the grammar.

Steps
-----

1. Create ``hydromodpy/cli/commands/<verb>.py`` with the four symbols.
2. Add the module to the import list and to ``ALL_COMMANDS`` in
   ``hydromodpy/cli/commands/__init__.py``. The order in the tuple is the order in
   ``hmp --help``.
3. Declare what the verb writes in ``OUTPUTS`` of ``hydromodpy/cli/output.py``. ``emit`` is
   the only function that writes JSON or CSV. A verb whose output is a document, such as a
   TOML file, has no entry and no ``--format``.
4. Add the tests below. The reference page is generated at every build, so it needs no edit.

Conventions
-----------

- The verb is in kebab-case, and ``NAME`` holds that form.
- The handler calls the verb of ``hydromodpy.project.api`` it stands for, and never
  ``import hydromodpy as hmp``. A verb needs ``workspace=``. The command passes ``-w``, or
  the project of its working directory, which only the command line reads.
- Expensive imports (``flopy``, ``zarr``, ``geopandas``) go inside the handler, so the CLI
  boots fast.
- ``stdout`` carries the result the user asked for. Diagnostics and progress go to
  ``stderr`` or to ``logging``.
- A destination is ``--to``, a preview is ``--dry-run``, a name is ``--name``, and a verb
  that removes something takes ``-y``. ``--force`` goes past a refusal that the verb makes
  because of what is already there, and the refusal names ``--force``.
- Let an exception propagate. The dispatcher prints its ``HMPY.Exxx`` and ends with
  ``exit_code_for``, which reads the ``category`` of the exception class in ``EXIT_CODE_OF``
  (``hydromodpy/cli/exit_codes.py``). A new exception sets its category once on its class.
  A refusal of the verb itself is ``refuse(message, EXIT_...)`` from the same module. Exit
  codes are 0 success, 1 generic, 2 usage, 10 to 23 for the categories and 130 for SIGINT.

Verbs that run a workflow
-------------------------

A verb that dispatches to a workflow takes the standard overlay flags (``--overlay``,
``--set``, ``--frozen``, ``--no-display``, ``--from``, ``--until``, ``--resume``), so the
precedence defaults, ``base_config`` chain, overlays, ``--set``, environment stays the same
everywhere. ``hmp run`` is the reference.

Families
--------

A verb with a lifecycle is a family. It is a sub-package of ``cli/commands/`` whose
``__init__.py`` carries ``NAME``, ``HELP``, an ``ACTIONS`` tuple and ``register``, with one
module per action that repeats the four symbols. ``hydromodpy/cli/commands/catalog/`` is the
reference. Attach the actions with ``add_action_subparsers``, so a bare ``hmp catalog`` is a
usage error and exits 2. A small verb can also nest its own ``add_subparsers``, as
``hmp config`` does.

``hmp check`` shows how thin a handler stays. Its ``run`` calls ``check`` of
``hydromodpy.project.api``, prints the diagnostics, or emits them under ``--format json``,
and ends with exit code 14 when one has the severity ``error``. Reading the file and the
rules between the sections happen below the command.

Tests to add
------------

- A unit test under ``tests/unit/cli/`` with ``argparse.Namespace`` assertions and a
  stubbed handler.
- An integration test under ``tests/integration/cli/`` that runs
  ``subprocess.run([sys.executable, "-m", "hydromodpy", ...])`` for one realistic call.

The layers that ``cli`` may import are in :doc:`../generated/layers`.

See also
--------

- :doc:`../packages/cli` for the package.
- :doc:`../mental-model` for the ``hmp run`` dispatch model.
