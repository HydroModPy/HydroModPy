Package: project
================

.. include:: ../../../../../hydromodpy/project/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: project

Inside the package
------------------

The fifteen verbs of ``api.py`` are the whole public surface. Each verb resolves its source or
its reference, calls the function of the package that does the work and returns a typed value.
The Python reference of the docs is built from their docstrings. ``show`` reads one line of
``show.SHOWN``, so a new value of ``what`` is a line of that table.

The trial pipeline is the one global that crosses to a lower layer. Calibration cannot import
``workflow`` or ``project``, so it defines the ``TrialPipeline`` protocol and
``trial_pipeline.py`` implements it. Each entry that reads the pipeline fills it first, which is
why the command line fills nothing. No other adapter is wired through a global.

``dispatch/`` holds the adapters that need the public ``Project`` and that lower layers must not
import. ``dispatch/workflow.py`` binds a workflow name to the call that runs it for ``hmp run``,
and ``rerun.py`` reruns a recorded run for ``hmp catalog rerun``. They are the one place in
``project`` that imports ``Project`` outside ``TYPE_CHECKING``, and only inside functions.
``launch/`` and ``exchange/`` never import it. ``exchange/`` carries a run between workspaces
(``share.py`` to publish, ``install.py`` to install, ``replay.py`` to replay), so it needs to see
both the run and the data of a workspace.

The launcher of a ``[sites]`` project plans many cases once, prepares them once, solves them as
separate processes and collects them into ``summary/``. The plan is written once under
``plan/<hash>/``, and it is the same plan for ``local.py`` and for SLURM (``slurm.py``). So a rule
that picks cases or sets a worker flag lives in ``selection.py`` only, and the two launchers
agree. ``prepare.py`` fetches the data of every case before any solve. ``status.py`` reads the
disk and never the index, and ``summary.py`` regenerates ``summary/`` from the run directories.

Where to add what
~~~~~~~~~~~~~~~~~

A new verb is a function of ``api.py``, and the command line calls it (see
:doc:`../how-to/add-a-cli-command`). A workflow name is a ``run_*`` function and an entry of
``DISPATCH`` in ``dispatch/workflow.py``, with the name in ``KNOWN_WORKFLOWS`` of
``workflow/dispatch.py``. A kind of file that a published run carries goes to
``exchange/share.py``, a check when installing to ``exchange/install.py`` and a check before a
replay to ``exchange/replay.py``. In the launcher, a table format or a binding rule of the plan
goes to ``plan.py``, a variable of a case environment to ``env.py``, a state that a case can be in
to ``status.py`` and a column of ``by_case`` or ``by_site`` to ``summary_tables.py``. A command
that a SLURM script calls is a function of ``slurm.py``, a branch of its ``main`` and a line of
the template, and the module path stays. A project is added to the example catalog by a line of
``WHITELIST`` in ``examples/generate.py`` once it runs end to end from a fresh workspace.
