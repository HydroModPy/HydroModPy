Add a CLI Command
=================

The ``hmp`` and ``hydromodpy`` CLIs share the same dispatcher in
``hydromodpy/cli/main.py``. Each verb is one module under
``hydromodpy/cli/commands/`` registered through ``ALL_COMMANDS`` in
``cli/commands/__init__.py``.

Today's verbs: ``init``, ``new``, ``config``, ``schema``, ``run``,
``dev``, ``catalog``, ``display``, ``report``, ``list``, ``export``,
``test``, ``data``, ``lock``, ``show``, ``compare``, ``add``,
``import``, ``doctor``, ``inspect``, ``manage``,
``install-binaries``, ``rank``, ``delete``, ``workspace``,
``completion``.

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

Files to create
---------------

Two edits.

**Create the module** ``hydromodpy/cli/commands/myverb.py``:

.. code-block:: python

   import argparse

   import hydromodpy as hmp


   NAME = "myverb"
   HELP = "Do my thing."


   def register(subparsers):
       parser = subparsers.add_parser(NAME, help=HELP)
       parser.add_argument("project", help="Project name or path.")
       parser.add_argument(
           "--workspace",
           default=None,
           help="Workspace root (default: ~/hydromodpy).",
       )
       parser.set_defaults(_handler=run)
       return parser


   def run(args):
       catalog = hmp.open(args.workspace)
       project = catalog.project(args.project)
       project.do_my_thing()

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
  subpackage (``calibration``, ``analysis``, ``results``, etc.).
- Import expensive subpackages (``flopy``, ``zarr``,
  ``geopandas``) **inside** the handler, not at the top of the
  module. The CLI must boot fast.
- Never write to ``stdout`` directly; use ``logging`` so ``--verbose``
  / ``--quiet`` work.
- Wrap user-facing errors in clear ``SystemExit`` messages; let
  unexpected errors propagate.

Workflow flags
--------------

If the verb dispatches to a workflow, accept the standard overlay
flags (``--overlay``, ``--set``, ``--frozen``, ``--no-display``,
``--from``, ``--until``, ``--no-checkpoint``, ``--resume``) so the
override precedence (defaults < ``base_config`` chain < overlays <
``--set`` < env) stays consistent. ``hmp run`` is the canonical
example.

Subcommands
-----------

When a verb has its own subcommands (``hmp config template``,
``hmp test regression``, ``hmp data list``), nest a second
``add_subparsers`` and reuse the same NAME / HELP / register / run
contract for each subcommand module.

Tests to add
------------

- **Unit** under ``tests/unit/cli/commands/`` with
  ``argparse.Namespace`` assertions and a stubbed handler.
- **Integration** under ``tests/integration/cli/`` with
  ``subprocess.run([sys.executable, "-m", "hydromodpy", ...])`` for
  one realistic invocation.

Update the docs
---------------

Add the verb to :doc:`/user_guide/cli-reference` (the canonical CLI
inventory). If the verb has its own option ladder, expand it there.

Pitfalls flagged by the layer matrix
------------------------------------

- ``cli`` may import everything; the freedom is intentional.
- ``cli`` -> ``<root>`` is documented as a tolerance: the CLI
  delegates to the public ``Project`` facade through the top-level
  ``hydromodpy`` package, not by importing private submodules.
- Do not implement business logic inside the command file. The CLI
  is a thin dispatcher; logic belongs to the relevant package so
  unit tests can exercise it without subprocess overhead.

See also
--------

- :doc:`../packages/cli` for the existing verb inventory.
- :doc:`../overview/mental-model-and-design-choices` for the
  ``hmp run`` dispatch model.
- :doc:`/user_guide/cli-reference` for the user-facing CLI page.
