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
``hydromodpy.project.api`` or the package that the verb serves, format the output and map errors
to exit codes. Reusable behaviour belongs in ``hydromodpy.project.api`` or in its domain
package. Work that a Python user needs too is a verb first, which the command then calls.

``hmp run`` calls the verb ``run`` for a simulation and an overview, and ``dispatch_workflow``
of ``project/dispatch/workflow.py`` for a calibration. This package never calls
``fill_trial_pipeline``. Each library entry that reads the pipeline fills it.

How a run starts
~~~~~~~~~~~~~~~~

``hmp run config.toml`` or ``hmp run request.json --base /project`` goes to ``commands/run.py``,
which builds the ``RunRequest`` with ``request_of`` of ``project/request.py``. A ``.json`` file
is the request itself, and ``--overlay`` is refused with it. ``--set``, ``--overlay`` and
``--case`` join the request. The command then calls ``project.api.run``, and the workflow is the
declared ``[workflow].mode`` or the one that the sections imply. An exception that leaves the
handler goes to ``fail`` in ``exit_codes.py``, which prints its message on stderr and exits with
the code of its class.

``--format table|json|csv`` is on every verb except the ones that print a document. Under
``json``, stdout holds one object and nothing else, because ``main.py`` points stdout at stderr
while the verb works and ``output.emit`` writes the result once it is over.

The grammar of a verb has a few fixed words. A destination is ``--to``, a preview is
``--dry-run``, a verb that removes something takes ``-y``, and a name is ``--name``.
``--force`` has one meaning, to go past a refusal because of what is already there or what
protects it, and it never skips a question.

Where to add what
~~~~~~~~~~~~~~~~~

- A leaf verb is a module of ``commands/`` with ``NAME``, ``HELP``, ``register`` and ``run``,
  named in ``ALL_COMMANDS`` of ``commands/__init__.py``. An action of a family is a module of
  the family sub-package with the same four symbols, listed in the ``ACTIONS`` tuple of its
  ``__init__.py``.
- A shared option is a parser of ``conventions.py``, passed through ``parents=``.
- A new verb declares what it writes in ``OUTPUTS`` of ``output.py``, and a form that moved gets
  its line in ``OLD_CLI_FORMS``.
- An exit code is a ``Category`` on the exception class, and a new category is a value of
  ``Category`` and a line of ``EXIT_CODE_OF``.

``tests/unit/cli/test_main.py`` walks ``ALL_COMMANDS``, checks the help of each verb and holds
the list of verbs the command line must expose, so a verb added or removed is a line there.
``tests/unit/cli/test_machine_output.py`` walks the tree for the grammar and the envelope. Start
reading at ``main.py``, then ``commands/run.py``, then ``project/api.py``.
