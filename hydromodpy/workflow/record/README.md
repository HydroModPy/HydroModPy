# `hydromodpy/workflow/record`

What a run writes about itself, and what is read back to resume or check it: the
claim of the run directory and its outcome, the store opened for one caller, the
step journal, the manifest that signs the step blueprint, and the resume plan.
Nothing here runs a step.

## Import rules

`workflow` may import every layer below it (`tests/unit/architecture/layer_matrix.yaml`).
Inside the package, `record/` imports `state` and `step` (and `core`, `results`) and
never `steps/`: `steps/` imports `record`, so the other way would be a cycle. That is
also why `replay_checks.py` sits at the root of `workflow`: it reads
`steps.prepare_solver.resolved`.

## Modules

In the order a run meets them.

| module | what it answers |
|---|---|
| `attempt.py` | one attempt of a run, from the claim of its directory to its outcome (`run_attempt`, `AttemptHandle`, `SealedRun`). The claim holds no identity. The handle restarts a resumed attempt when the `request_id` changed (`start_over_if_changed`), and `withdraw()` marks an attempt to be undone instead of closed, so a run identical to a sealed one leaves no directory and no outcome behind |
| `run_store.py` | the `RunStore` of a run, opened for the span of one caller (`run_store`, `run_is_persisted`, `run_dir_of_state`) |
| `journal.py` | the step journal `<run>/.hmp/checkpoints/steps.json` (`WorkflowJournal`, `WorkflowStepRow`) |
| `manifest.py` | the resolved run manifest: the step blueprint and the config digest that a resume must match (`ResolvedRunManifest`) |
| `resume.py` | which step a run resumes from, read from the journal (`ResumePlanner`, `resolve_resume_step_index`, `scratch_of_resumed_run`) |

## Tree

```
record/
  attempt.py    claim, run, outcome
  run_store.py  the store of a run
  journal.py    steps.json
  manifest.py   resolved_manifest.json
  resume.py     where to resume
```

## Where to add what

| to add | where |
|---|---|
| a column of the step journal | `WorkflowStepRow` in `journal.py` (and `JOURNAL_SCHEMA` if the format changes) |
| something the manifest must match at resume | `manifest.py` |
| a rule for choosing the resume step | `resume.py` |
| a state of the attempt (claim, heartbeat, outcome, withdrawal) | `attempt.py` |
| a new kind of artifact a step can name | `collect_artifacts` in `workflow/runner.py` |
