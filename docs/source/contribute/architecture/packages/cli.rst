Package: cli
============

.. include:: ../../../../../hydromodpy/cli/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: cli

Inside the package
------------------

A command calls a verb. ``commands/*.py`` parse arguments, call one verb of
``hydromodpy.project.api`` or the package that the verb serves (``results.catalog``,
``data.request``, ``display``, ``project.data_cache``), format the output and map errors to
exit codes. Reusable behaviour belongs in ``hydromodpy.project.api`` or in its domain
package, and work that a Python user needs too is a verb first, which the command then
calls. Most commands share the name of their verb, with the options of the command line,
the recap and the exit code added. The commands that differ are ``ls``, which calls
``status`` with ``--plan`` and ``--disk`` and reads the filters of the index through
``list_runs`` of ``results.catalog.listing``, ``show``, which has one selector per value of
``what`` and resolves the reference with ``show_target`` of ``project.show``, ``diff``,
which calls ``compare`` and writes the folder named by ``compare_folder`` of
``project.compare`` when ``--to``, ``--by`` or ``--variables`` is given, ``example``, where
``add`` installs and the other two read the catalog, and ``catalog trash`` and
``catalog restore``, which call ``trash``. The rows of ``doctor`` are built by
``project.doctor`` and the command prints them.

``hmp run`` calls the verb ``run`` for a simulation and an overview, and
``dispatch_workflow`` of ``project/dispatch/workflow.py`` for a calibration.
``fill_trial_pipeline`` is not called in this package. Each library entry that reads the
pipeline fills it: the calibration verbs, ``route_calibration``, ``promote_trial`` behind
``campaign promote`` and ``rerun_config`` behind ``catalog rerun``. A ``[sites]`` child is
a ``hmp run``.

How a run starts. ``hmp run config.toml`` or ``hmp run request.json --base /project`` goes
to ``commands/run.py``, which builds the ``RunRequest`` with ``request_of`` of
``project/request.py``. A ``.json`` file is the request itself, and ``--overlay`` is refused
with it. ``--set``, ``--overlay`` and ``--case`` join the request. The command then calls
``project.api.run(request, base=, environment=)``, and the workflow is the declared
``[workflow].mode`` or the one that the sections imply. ``run_simulation`` loads the
config, checks the name, claims the run directory, writes ``request.json`` and
``config.toml``, resolves the inputs and the ``request_id``, restarts or skips, and then
plays the pipeline. An exception that leaves the handler goes to ``exit_codes.fail`` in
``main.py``, which prints its code and its message on stderr and exits with the code of its
class.

What a program reads. ``--format table|json|csv`` is on every verb except the ones that
print a document (``config template``, ``resolve``, ``schema``, ``wizard`` and
``completion``). Under ``json``, stdout holds one object and nothing else, because
``main.py`` points stdout at stderr while the verb works and ``output.emit`` writes the
result once it is over. The page ``reference/cli/machine-output`` is generated from
``OUTPUTS``, the page ``reference/cli/exit-codes`` from the categories and the exceptions
behind them, and the page of each verb from its parser.

The grammar of a verb has a few fixed words. A destination is ``--to``, a preview is
``--dry-run``, a verb that removes something takes ``-y``, and a name is ``--name``. The
file format of ``export`` is ``--as`` and the container of ``publish`` is ``--container``.
``--force`` has one meaning, to go past a refusal that the verb makes because of what is
already there or what protects it, and it never skips a question.

Where to add what. A leaf verb is a module of ``commands/`` with ``NAME``, ``HELP``,
``register`` and ``run``, named in the import list and in ``ALL_COMMANDS`` of
``commands/__init__.py``. An action of a family is a module of the family sub-package with
the same four symbols, listed in the ``ACTIONS`` tuple of its ``__init__.py``. A shared
option is a parser of ``conventions.py``, passed through ``parents=``. A new verb declares
what it writes in ``OUTPUTS`` of ``output.py``, and a form that moved gets its line in
``OLD_CLI_FORMS``. Work behind a command is a function of the package it serves. An exit
code is a ``Category`` on the exception class, and a new category is a value of
``Category`` and a line of ``EXIT_CODE_OF``.

Three tests guard the package. ``tests/unit/cli/test_cli_help.py`` walks ``ALL_COMMANDS``
and checks the help of each verb. ``tests/unit/cli/test_cli_surface_matches_the_target.py``
holds the list of verbs and actions that the command line must expose and the ones it must
not, so a verb added or removed is a line there. ``tests/unit/cli/test_machine_output.py``
walks the tree for the grammar and the envelope. Start reading at ``main.py`` for the
dispatch loop, then ``commands/__init__.py``, then ``commands/run.py`` for the canonical
workflow verb, then ``project/api.py`` for the verbs and ``project/dispatch/workflow.py``
for the table from mode to launcher, and last a small command such as ``commands/stop.py``.
