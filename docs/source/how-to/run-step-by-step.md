# Run step by step

A run can stop after any step and continue later. This page shows how I look at the ground of a model before the solve, draw a figure at that point and then finish the run. To build a model in memory and change it, see [Work in the lab](work-in-the-lab.md).

## Stop at a step

`hmp.run(project, until_step="prepare_solver", name="demo")` plays the steps up to `prepare_solver` and stops. It gives back an outcome, and `hmp.open(outcome.run_dir)` opens the partial run. `run.steps` lists the steps done, from `validate` to `prepare_solver`, and `run_solver` is not in it. The run has no seal yet.

`run.read("topography")` then reads the ground of every cell, before any solve. This works for a backend that builds a cell column. The heads do not exist yet, so reading them is refused.

## Draw a figure at that step

A figure of the `[[display.figure]]` table says when it is drawn with `when`. The value `"after:prepare_solver"` draws it as soon as that step is done. A figure whose data comes at `extract`, such as the heads, cannot be drawn there. `hmp.check` refuses it and names the step.

```toml
[display]
enabled = true

[[display.figure]]
variable = "topography"
when = "after:prepare_solver"
```

## Continue and seal

`hmp.run(project, name="demo")` with the same name continues the run in place. It plays the steps that are missing and seals the run. Nothing is played twice.

Each window is one attempt on the same run folder, and the sealed run records the number of the last attempt.

## Play it again

If I play the same calls again with no change, each window gives back the run already done. No new version such as `demo_v2` appears. This holds when I do not pass `from_step`, `resume` or `force`.

## An example

The lines below come from a test that runs on every change.

```{literalinclude} /../../tests/scenarios/test_a_run_stops_resumes_and_chains.py
:start-after: "# [windows-walkthrough]"
:end-before: "# [/windows-walkthrough]"
:language: python
```
