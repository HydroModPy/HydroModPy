Add a CLI command
=================

The ``hmp`` and ``hydromodpy`` CLIs share the same dispatcher in
``hydromodpy/cli/main.py``. Each verb is one module under
``hydromodpy/cli/commands/`` registered through ``ALL_COMMANDS`` in
``cli/commands/__init__.py``.

Today's verbs, in ``ALL_COMMANDS`` order: ``workspace``, ``project``,
``campaign``, ``example``, ``catalog``, ``data``, ``export``, ``publish``,
``viz``, ``config``, ``lock``, ``completion``, ``privacy``, ``run``,
``calibrate``, ``spinup``, ``site``, ``report``, ``doctor``,
``install-binaries``. That tuple is the inventory; anything not in it is not a
verb.

Nine of them are families, not leaves: ``workspace``, ``project``,
``campaign``, ``example``, ``catalog``, ``data``, ``lock``, ``viz`` and ``site``
are sub-packages whose ``__init__.py`` carries ``NAME``, ``HELP`` and an
``ACTIONS`` tuple.

Contract
--------

Each command file exposes:

.. code-block:: python

   import argparse


   NAME: str = "myverb"
   HELP: str = "Short one-line description."


   def register(subparsers) -> argparse.ArgumentParser:
       parser = subparsers.add_parser(NAME, help=HELP)
       parser.add_argument("target", help="Positional argument.")
       parser.add_argument("--option", default=None)
       parser.set_defaults(_handler=run)
       return parser


   def run(args: argparse.Namespace) -> None:
       """Handler called by the dispatcher."""
       ...

The dispatcher iterates ``ALL_COMMANDS``, calls ``register`` on each,
and forwards the parsed namespace to ``args._handler``.

Reuse the shared grammar from ``hydromodpy/cli/conventions.py`` instead
of re-declaring flags: ``workspace_parser()`` for ``-w/--workspace``,
``confirm_parser()`` for ``-y/--yes``, ``dry_run_parser()`` for
``--dry-run``, ``format_parser()`` for ``--format {table,json,csv}``,
``add_destination()`` for ``--to``, ``add_sim_ref()`` for the canonical
``sim_ref`` positional. ``tests/unit/cli/test_machine_output.py`` walks
the argparse tree and fails on a verb without ``-w`` or ``--format``, or
with a flag that left the grammar.

Files to create
---------------

Two edits.

**Create the module** ``hydromodpy/cli/commands/myverb.py``:

.. code-block:: python

   import argparse

   import hydromodpy as hmp
   from hydromodpy.cli.conventions import format_parser, workspace_parser
   from hydromodpy.cli.helpers import resolve_workspace
   from hydromodpy.cli.output import emit


   NAME = "myverb"
   HELP = "Do my thing."


   def register(subparsers):
       parser = subparsers.add_parser(
           NAME,
           help=HELP,
           parents=[workspace_parser(), format_parser()],
           epilog="Example:\n  hmp myverb my_project -w ~/hydromodpy",
           formatter_class=argparse.RawDescriptionHelpFormatter,
       )
       parser.add_argument("project", help="Project name.")
       parser.set_defaults(_handler=run)
       return parser


   def run(args):
       workspace = hmp.open(resolve_workspace(args.workspace))
       project = workspace[args.project]
       written = project.do_my_thing()
       emit(args, "myverb", {"path": written}, table=lambda: print(f"wrote {written}"))

**Declare what it writes** in ``OUTPUTS`` of ``hydromodpy/cli/output.py``. ``emit`` is the only
function that writes JSON or CSV, and the page on what a program reads is generated from that
table. A verb whose output is a document, such as a TOML file, has no entry and no ``--format``.

**Register it** in ``hydromodpy/cli/commands/__init__.py``:

.. code-block:: python

   from . import myverb  # noqa: F401

   ALL_COMMANDS = (
       ...,
       myverb,
   )

Order in ``ALL_COMMANDS`` controls the order in ``hmp --help``.

Conventions
-----------

- Use kebab-case for the verb (``my-verb`` becomes ``NAME =
  "my-verb"``).
- Keep the handler thin: defer business logic to the relevant
  subpackage (``calibration``, ``project``, ``results``, etc.).
- Import expensive subpackages (``flopy``, ``zarr``,
  ``geopandas``) **inside** the handler, not at the top of the
  module. The CLI must boot fast.
- ``stdout`` carries the result the user asked for; diagnostics and
  progress go to ``stderr`` or through ``logging``. Under ``--format
  json`` the dispatcher keeps stdout for what ``emit`` writes.
- A destination is ``--to``. A preview is ``--dry-run``. A verb that
  removes something takes ``-y``. ``--force`` means one thing: go past
  a refusal the verb makes because of what is already there or what
  protects it, and the refusal names ``--force``. A name is ``--name``.
- Let an exception propagate: the dispatcher prints its ``HMPY.Exxx``
  and ends with ``exit_code_for``. A refusal of the verb itself is
  ``hydromodpy.cli.helpers.refuse(message, EXIT_...)``. Exit codes are
  0 success, 1 generic, 2 usage, 10..23 specific failure categories,
  130 SIGINT.

Workflow flags
--------------

If the verb dispatches to a workflow, accept the standard overlay
flags (``--overlay``, ``--set``, ``--frozen``, ``--no-display``,
``--from``, ``--until``, ``--resume``) so the override precedence
(defaults < ``base_config`` chain < overlays < ``--set`` < env) stays
consistent. ``hmp run`` is the canonical example; it also carries
``--dry-run``, ``--force``, ``--no-parallel`` and
``--profile``.

Subcommands
-----------

A verb with a handful of actions nests a second ``add_subparsers`` in
its own module: ``hmp config template``, ``hmp config check``,
``hmp report render``.

A verb with a whole lifecycle becomes a **family**: a sub-package under
``cli/commands/`` whose ``__init__.py`` declares ``NAME``, ``HELP`` and
an ``ACTIONS`` tuple, with one module per action following the same
four-symbol shape. ``hmp catalog`` (``ls``, ``query``, ``show``,
``point``, ``rank``, ``gc``, ``reindex``, ``delete``, ``restore``, ``trash``,
``tag``, ``note``, ``rename``, ``diff``, ``watch``, ``import``,
``rerun``) is the reference. Attach the group with
``add_action_subparsers`` so a bare ``hmp catalog`` is a usage error and
exits 2.

Tests to add
------------

- **Unit** under ``tests/unit/cli/`` with ``argparse.Namespace``
  assertions and a stubbed handler.
- **Integration** under ``tests/integration/cli/`` with
  ``subprocess.run([sys.executable, "-m", "hydromodpy", ...])`` for
  one realistic invocation.

Update the docs
---------------

Add the verb to :doc:`/reference/cli/index` (the canonical CLI
inventory). If the verb has its own option ladder, expand it there.

Pitfalls flagged by the layer matrix
------------------------------------

- ``cli`` may import any stable production layer, plus ``catalog`` and
  ``project``. It must not depend on experimental ``validity_frame``
  tooling.
- Do not implement business logic inside the command file. The CLI
  is a thin dispatcher; logic belongs to the relevant package so
  unit tests can exercise it without subprocess overhead.

See also
--------

- :doc:`../packages/cli` for the existing verb inventory.
- :doc:`../mental-model` for the ``hmp run`` dispatch model.
- :doc:`/reference/cli/index` for the user-facing CLI page.
