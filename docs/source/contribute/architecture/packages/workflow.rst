Package: workflow
=================

.. include:: ../../../../../hydromodpy/workflow/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: workflow

Inside the package
------------------

The root. ``dispatch.py`` says which workflow a file runs, from ``KNOWN_WORKFLOWS``, the
declared ``[workflow] mode`` or the one that the sections imply. ``window.py`` says which
steps a run executes, from ``from_step``, ``until_step`` and the model phase.
``state.py`` holds ``PipelineState``, which flows from step to step. ``step.py`` holds the
``Step`` protocol, a runtime-checkable protocol of ``name`` and ``run``. ``reads``,
``writes`` and ``config_sections`` are class variables of each step, and
``earliest_affected_step`` of ``steps/dependencies.py`` reads ``config_sections``.
``runner.py`` holds ``Pipeline(steps, workspace=..., run_dir=...)``. It runs the steps,
writes the journal, names the current step to the heartbeat, resumes, checks the resolved
manifest, reads the stop flag before each cohort and writes one line of ``profile.json``
per step. When the pipeline has no run directory, as in a calibration trial, the lines go
into the collector of ``results.storage.run_profile``. ``dag.py`` builds the step graph from
``depends_on()`` and sorts it into cohorts, ``parallel.py`` runs a cohort, ``overview.py``
holds the launcher of the data overview, the identity card of a watershed, without a solver
run, ``solution_key.py`` tells when two runs are the same, and ``products.py`` asks the
product store once per kind.

The thirteen steps. ``standard_steps()`` of ``steps/sequence.py`` returns them in this
order, with the names of ``core/pipeline_steps.py``. Each step declares the step it depends
on, so the graph is a chain and every cohort holds one step. ``validate`` (``validate.py``)
checks the file before anything is built. ``resolve`` (``resolve.py``) gives the workspace
paths and the ``WorkflowContext``. ``build_geographic`` and ``setup_process`` (``setup.py``)
build the geographic context, the domain and the spatial supports, then the process objects
``Flow`` and ``Transport`` and the solver scratch of the attempt. ``load_data`` (``data.py``)
loads the data of ``[data]`` and binds it to the runtime. ``build_mesh`` (``mesh.py``) builds
the cell mesh of the engine of ``[mesh]``. ``prepare_solver`` (``prepare_solver/``) makes
the simulation plan, binds the run directory, records the facts of the run and freezes the
configuration into ``config.toml`` and ``config.resolved.toml``. ``run_solver``
executes the plan with ``SimulationRunner``. ``extract`` reads the solver files into the
store of the run and ingests the observations, and ``derive`` computes the catchment
aggregates, the observation points and the fit metrics, both through the functions of
``run_outputs.py``. ``export`` drops the solver files and cleans the scratch, ``seal``
writes the seal, and ``step_after_seal`` writes the ``[[export]]`` data requests and the
views from the sealed run. ``display`` then draws the figures of ``[display]`` from the
sealed run with its label.

How a run goes through it. First the launcher claims the directory of the case under
``runs/`` through ``record/attempt.py``, before the first step. ``outcome.json`` says
``running``, a heartbeat pulses and the scratch of the attempt is named, and the state
carries ``run_dir``. ``standard_steps()`` makes the thirteen steps and ``Pipeline`` builds
the graph from ``depends_on()``. ``Pipeline.run(state, resume_from=..., parallel=...,
heartbeat=...)`` takes an initial ``PipelineState``, and each step is ``state.advance(...)``
over the shared payload, whose dominant member is the ``WorkflowContext``. A cohort of
several steps would go through a thread pool, but the thirteen steps give only single-step
cohorts.

Each step is recorded in ``<run>/.hmp/checkpoints/steps.json`` with the hash of its
artifacts. ``ResolvedRunManifest`` records the step blueprint and the config digest beside
it, in ``resolved_manifest.json``, and the facts of the run (``RunFacts``) accumulate in
``facts.json`` of the same folder. A step that writes durable artifacts implements
``artifacts(state_out)`` and ``rebuild_state(...)``. At resume the runner rebuilds the state
of a completed step from disk and does not run it again. There is no pickle layer and no
checkpoint store, so resume reads artifacts, as :doc:`../pipeline_resume` tells. Before each
cohort the runner reads the stop flag of the run, ``.hmp/stop.json``, and raises
``StopRequested`` when it is there. The step that a stop interrupts is marked ``aborted`` in
the journal, so a resume plays it again from its start, ``run_solver`` included. A product
read from the project store is a ``store`` line of the profile, and a step rebuilt from an
earlier attempt is a ``prefix`` line.

``SealStep`` writes the seal from the facts. The pipeline then writes the journal row of the
seal and its checkpoint, and the attempt protocol around the pipeline finds the seal, flips
the outcome to ``completed`` and removes ``<run>/.hmp/``. The data exports and the views, and
then the figures, follow the seal and carry its label. A render that raises after the seal
leaves the run sealed and ``completed``, because the attempt protocol closes it with
``close_sealed_attempt`` and the error goes up. A run that stops before the seal keeps the
outcome that the attempt protocol wrote, which is ``failed``, ``aborted`` or ``partial`` for
a window ended by ``--until``, and its attempt state. ``ProjectRunner.execute`` bounds the
step window with ``from_step`` and ``until_step``. A calibration trial skips the shared
steps, because it asks ``earliest_affected_step`` for the first step that an override reaches,
from the ``config_sections`` of the steps.

The imports. Inside the package, ``steps/`` imports ``record``, ``state``, ``step`` and
``runner``, and ``runner.py`` imports ``dag``, ``parallel``, ``state``, ``step`` and
``record``. ``record/`` imports ``state`` and ``step`` and never ``steps``. A step's ``reads``
and ``writes`` are exact. ``tests/unit/architecture/test_run_path.py`` derives both from the
source of the step, fails when a declaration and the code disagree in either direction, and
requires every member of ``WorkflowContext`` to have a reader. A step never opens the index
of the project. It writes through ``run_store(ctx)`` into the directory of the run, and the
launcher derives the index once the worker has returned.

Where to add what. A step is described in the docstring of ``steps/__init__.py``, with its
name in ``core/pipeline_steps.py``. Something that a run records about itself goes to
``record/``. A fact of the run is a field of ``RunFacts`` in ``results/storage/run_facts.py``
and the block of the seal it feeds in ``results/storage/sealing.py``. A derived field is a
row of ``VIRTUAL_FIELD_ROWS`` in ``results/derive/virtual_fields.py``, rebuilt on read and
never written by a step. A workflow mode is a name in ``KNOWN_WORKFLOWS`` and its adapter in
``project/dispatch/workflow.py``. A standalone launcher is a class next to ``overview.py``,
built on the steps it needs, and a check at replay is a function of ``replay_checks.py``.
