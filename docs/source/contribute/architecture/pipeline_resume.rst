Pipeline resume from artifacts
==============================

The simulation pipeline rebuilds its in-memory state exclusively from
durable artifacts and the TOML config. There is no pickle layer, no
``CheckpointStore``, and no signed-blob deserialization. Resume relies on
three sources of truth:

#. ``<run>/.hmp/checkpoints/resolved_manifest.json``: tracks the step
   blueprint, the config SHA-256, and the cursor.
#. ``<run>/.hmp/checkpoints/steps.json``: per-step inputs/outputs hashes,
   ``artifact_uris`` and status.
#. The Zarr arrays and Parquet tables of the run directory.

All three live in the run directory, with the attempt state that the seal of
a completed run removes. None is in the index: a run never opens it.

Invariant
---------

  *Pipeline state at step N is a pure function of the persisted
  artifacts produced by steps 0 to N-1, plus the resolved config.*

Any step that produces durable output declares both ``artifacts(state)``
(workspace-relative URIs) and ``rebuild_state(prior_state, workspace,
run_id)``. The first method drives ``outputs_hash`` in the journal; the
second one reconstructs the next ``PipelineState`` by reading those same
artifacts (Zarr handles, Parquet tables, exports) without
re-running the heavy operation.

Two-phase execution
-------------------

``Pipeline.run`` operates in two phases:

* **Rebuild phase** ``[0, restart_index)``: every step either gets
  re-executed (cheap, idempotent: validate, resolve, geographic, data,
  mesh, setup) or its output state is rebuilt from artifacts
  (``prepare_solver``, ``run_solver``, ``extract``, ``export``). The
  journal is not written during this phase.
* **Execute phase** ``[restart_index, end)``: each step runs fully; the
  journal records inputs/outputs hashes and the heartbeat pulses in
  ``logs/heartbeat.json``.

Resume integrity
----------------

Before any work starts, two guards check that the workspace has not
drifted:

* ``ResolvedRunManifest.verify_state`` compares the blueprint and the
  config SHA-256 with what was written at the previous attempt. A
  mismatch raises :class:`hydromodpy.core.exceptions.ResumeError`.
* ``ResumePlanner.compute`` checks every completed row in
  ``steps.json``: artifacts must still exist and ``outputs_hash``
  must match a recomputed digest. Any divergence cascade-invalidates the
  rows from the offending step onwards and the runner restarts there.

When ``resume_from`` is ``None`` (or 0), the runner first calls
``WorkflowJournal.invalidate_from(start_order=0, reason="from_scratch")``
so a stale journal from a reused ``run_id`` cannot leak into the new run.

Resume across attempts
----------------------

The journal belongs to the attempt in progress, under ``<run>/.hmp/``, and the
attempt protocol of :doc:`storage-layout` decides when it is read again. A new
attempt of a failed case resumes in place by default: the checkpoints stay, so
the runner restarts at the first step the journal does not cover. ``--fresh``,
or a config hash that changed, files the whole earlier attempt under
``attempts/<k>/`` and starts from scratch. The step window serves the
launcher of a ``[sites]`` project too: its ``prepare`` phase runs each case up
to its data (``--until load_data``) to fill the workspace input cache, and the
worker that solves the case later reads its inputs from that cache with
``--frozen``.

Stopping a run
--------------

A stop can be asked from outside a process, without a signal. ``hmp stop REF``
(``hmp.stop``) calls ``request_stop`` of ``results/storage/attempt.py``, which
writes ``<run>/.hmp/stop.json`` for a run that is running and refuses a run in
any other state, with the state it read. A session of calibration has the same
flag under ``<session>/.hmp/``. The flag is read at the places where an
unwinding does no harm.

* The pipeline reads it before each cohort of steps, so a stop falls between
  two steps and also just before the seal.
* The runner of the plan reads it between two runs of the plan. MODFLOW 6
  through libmf6 reads it at the end of each time step, and the Boussinesq
  solver between two periods. A backend that solves through an executable reads
  nothing, because killing the child would leave half-written files, and the
  flag is read after its solve.
* The calibration engine reads it before each ``ask``, so the trials of the
  batch in flight finish and are journaled.

``StopRequested`` is a ``KeyboardInterrupt``, so the attempt hook, the line of
the step journal and the closing of a session treat it as they treat a signal.
The run ends ``aborted`` with ``error.type = "StopRequested"``, no signal, no
seal, and the line of the step it stopped in is ``aborted``. A stop reads
``aborted`` in the vocabulary of the outcome and differs from a signal by that
error type. A session records ``stop requested at <date>`` as its error.

The flag belongs to the attempt in progress. The next attempt of a run files it
under ``attempts/<k>/stop.json``, so it does not stop at its first check and the
history keeps who stopped the run and when. A session has no ``attempts/<k>/``
folder, so reopening it removes the flag, and the date stays in the error of the
session until then.

Resuming a stopped run
----------------------

``hmp run --resume REF`` continues attempt ``k`` on the same ``request_id``. It
compares the ``request_id`` of the request with the one the outcome of attempt
``k`` recorded under ``attempts/<k>/``. The request id counts the resolved
configuration, the digests of the inputs and the state a window starts from, so
it sees what ``verify_state`` does not. When they differ, ``refuse_resume_if_changed``
raises ``ResumeError`` and says an input or a key changed since the stop. The check
of ``ResolvedRunManifest`` stays as a second guard. A plain ``hmp run`` without
``--resume`` resumes in place when the request is equal and starts over when it is
not.

A stop in the solve leaves the ``run_solver`` row ``aborted``, so the resume plays
``run_solver`` again from its start, the build of the solver files included. A stop
between two steps resumes at the next step. The steps before the stopped one are
rebuilt from their artifacts, and their lines in ``profile.json`` read
``reused = "prefix"``.

Windows
-------

``[simulation.time] window_length`` cuts a transient run into windows that end on
a stress period end. ``project/windows.py`` plays them in order. Each window is a
run of its own, named ``<name>_w1``, ``<name>_w2`` (two digits from ten windows),
that goes through the same claim, request, pipeline and seal as any run. The
cut is made by ``project/phases.py``, which gives ``setup.time_grid`` the periods
of the window and keeps the grid of the whole simulation in
``setup.whole_time_grid``. The data and the soil reservoir run on the whole grid, so a
window takes the same forcing as the run in one piece.

Window ``k > 1`` starts from the ``final_state/`` of window ``k - 1``. The pipeline
receives it as ``window_source``, ``prepare_solver`` reads it into ``Model.initial``
as a ``PriorState``, and ``inputs.json`` gets a line with ``variable = "initial_state"``
and ``provider = "run"``, whose digest is the one the ``request_id`` counts. A source
that is absent, or that was played with another request, is refused before the claim.

A window already sealed with the same request is skipped. After a stop in window 3,
``hmp run`` gives back windows 1 and 2, resumes window 3 in place at ``run_solver``,
and plays the windows after it.

Step contract recap
-------------------

.. code-block:: python

   class Step(Protocol):
       name: str
       reads: ClassVar[tuple[str, ...]]
       writes: ClassVar[tuple[str, ...]]

       def run(self, state_in: PipelineState) -> PipelineState: ...

       def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
           """Workspace-relative paths of durable outputs. Empty tuple = in-memory."""

       def rebuild_state(
           self,
           *,
           prior_state: PipelineState,
           workspace: Path,
           run_id: str,
       ) -> PipelineState:
           """Restore the output state from disk. Must not re-run the heavy op."""

In-memory steps (no ``artifacts``) are simply re-executed at resume:
they must stay idempotent and fast.

Surviving a process death
-------------------------

A resume exists for the deaths that run no handler: a lost machine, the
OOM killer, a canceled job. Nothing is flushed on the way out, so what
the next process can do is decided entirely by what the disk already
holds.

Two consequences follow, and both are gated by
``tests/e2e/test_resume_through_a_process_death.py``, which kills its own
child with ``SIGKILL`` twice.

* The step that was running when the process died keeps the status
  ``running``, not ``failed``. ``failed`` is what an exception writes.
  ``ResumePlanner`` restarts at that step either way.
* The journal has to be readable afterwards. ``steps.json`` and the facts of
  the run are rewritten through a temporary file and a rename, so a death
  between two writes leaves the previous document whole, and the next attempt
  of the same directory reads what the dead one recorded. No database is
  involved: a run never opens the project index, so there is no write-ahead
  log to poison.
