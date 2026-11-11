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

The fifteen verbs of ``api.py`` are the whole public surface, and its ``__all__`` holds
these fifteen. Each verb resolves its source or its reference, calls the function of the
package that does the work and returns a typed value. The docstring of each verb says what
it does, and the Python reference of the docs is built from them. ``show`` reads one line
of ``show.SHOWN``, so a new value of ``what`` is a line of that table.

The trial pipeline is the one global that crosses to a lower layer. Calibration cannot
import ``workflow`` or ``project``, so it defines the ``TrialPipeline`` protocol and
``trial_pipeline.py`` implements it. Each entry that reads the pipeline fills it first,
which is why the command line fills nothing. No other adapter is wired through a global.
``replay.py`` plays a sealed run or a published copy again and classes what it compared.
``report.py`` is the one place that assembles the texts of a run (``results/method.py`` and
``schema/phrases.py``) and its pages (``display/report/``). ``windows.py`` cuts a long
transient run into windows and plays them one after the other, and ``spinup.py`` repeats
a forcing window until the state settles.

The folders. ``dispatch/`` holds the adapters that need the public ``Project`` and that
lower layers must not import. ``workflow.py`` binds a workflow name (``simulation``,
``overview`` or ``calibration``) to the call that runs it for ``hmp run`` and ``hmp.run``,
and ``rerun.py`` reruns a recorded run through a ``Project`` for ``hmp catalog rerun``. It
is the one place in ``project`` that imports ``Project`` outside ``TYPE_CHECKING``, and only
inside functions. ``launch/`` and ``exchange/`` never import it. ``exchange/`` carries a run
between workspaces in three steps, ``share.py`` to publish, ``install.py`` to install and
``replay.py`` to replay, and it needs to see both the run and the data of a workspace.
``examples/`` holds what ``hmp example`` stands on, the catalog ``catalog.toml``, which is
generated and ships inside the wheel, the cache the example files are fetched into, and the
install into a workspace. The cache is keyed by file, so a blob that two examples share is
downloaded once. Blobs live at ``<cache>/examples/blobs/<sha256[:2]>/<sha256>``, beside the
solver binaries. Of the 92 MiB that example 04 needs, the regional DEM is 90 MiB.

The launcher of a ``[sites]`` project. Many cases, one per site and recipe, are planned
once, prepared once, solved as separate processes and then collected into ``summary/``.
``plan.py`` turns the ``[sites]`` section into one case per site and recipe. The site
table is CSV, Parquet or GeoPackage, and ``[sites.bind]`` binds its columns to dotted keys.
The plan is written once under ``plan/<hash>/`` and it is the same plan for the local
launcher and for SLURM. ``lease.py`` allows one launcher per project, ``selection.py``
chooses the cases and the worker flags, ``env.py`` gives a case its environment and thread
budget, ``children.py`` starts the workers and closes what a silent death leaves,
``prepare.py`` fetches the data of every case before any solve into the one ``data/``
folder of the project, and ``lockfile.py`` writes ``hydromodpy.lock`` from the sidecars
once that phase is over. ``local.py`` runs the plan on this machine, ``slurm.py`` and
``slurm_script.py`` write the SLURM array, ``sacct.py`` reads what ``sacct`` says of its
tasks, and ``journal.py`` keeps the trace under ``jobs/``. ``status.py`` says where each
case stands, read from the disk and never from the index. ``summary.py`` regenerates
``summary/`` from the run directories, with the tables of ``summary_tables.py`` and the
exports of ``summary_exports.py``.

Where to add what. A new verb is a function of ``api.py``, and the command line calls it
(see :doc:`../how-to/add-a-cli-command`). A workflow name is a ``run_*`` function and an
entry of ``DISPATCH`` in ``dispatch/workflow.py``, with the name in ``KNOWN_WORKFLOWS`` of
``workflow/dispatch.py``. A kind of file that a published run carries goes to
``exchange/share.py``, a check or a conflict when installing to ``exchange/install.py``,
and a check before a replay to ``exchange/replay.py``. In the launcher, a table format, a
binding rule or a budget ceiling of the plan goes to ``plan.py``, a rule that picks cases
or sets a worker flag to ``selection.py`` so that the local and the SLURM launch agree, a
variable of a case environment to ``env.py``, a state that a case can be in to ``status.py``
and a column of ``by_case`` or ``by_site`` to ``summary_tables.py``. A command that a SLURM
script calls is a function of ``slurm.py``, a branch of its ``main`` and a line of the
template, and the module path stays. A project is added to the example catalog by a line of
``WHITELIST`` once it runs end to end from a fresh workspace.
