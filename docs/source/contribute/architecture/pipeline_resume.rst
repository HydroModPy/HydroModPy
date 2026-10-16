Pipeline resume from artefacts
==============================

The simulation pipeline rebuilds its in-memory state exclusively from
durable artefacts and the TOML config. There is no pickle layer, no
``CheckpointStore``, and no signed-blob deserialisation. Resume relies on
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
  artefacts produced by steps 0 to N-1, plus the resolved config.*

Any step that produces durable output declares both ``artifacts(state)``
(workspace-relative URIs) and ``rebuild_state(prior_state, workspace,
run_id)``. The first method drives ``outputs_hash`` in the journal; the
second one reconstructs the next ``PipelineState`` by reading those same
artefacts (Zarr handles, Parquet tables, exports) without
re-running the heavy operation.

Two-phase execution
-------------------

``Pipeline.run`` operates in two phases:

* **Rebuild phase** ``[0, restart_index)``: every step either gets
  re-executed (cheap, idempotent: validate, resolve, geographic, data,
  mesh, setup) or its output state is rebuilt from artefacts
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
  ``steps.json``: artefacts must still exist and ``outputs_hash``
  must match a recomputed digest. Any divergence cascade-invalidates the
  rows from the offending step onwards and the runner restarts there.

When ``resume_from`` is ``None`` (or 0), the runner first calls
``WorkflowJournal.invalidate_from(start_order=0, reason="from_scratch")``
so a stale journal from a reused ``run_id`` cannot leak into the new run.

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
OOM killer, a cancelled job. Nothing is flushed on the way out, so what
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
