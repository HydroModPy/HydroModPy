# Work in the lab

`hmp.Lab` builds a model in memory, one step at a time, and lets you look at it, change it and solve it again. Use it when you write or debug a model from Python. Use `hmp.run` when the configuration is ready and you want a stored run.

A lab opens a `Project` and plays the same steps a run plays, from `validate` to `run_solver`. It writes no run folder and seals nothing. `lab.project` gives the project back, so a calibration or a spin-up still goes through it. The reference page of [Lab](../reference/python/Lab.md) lists every member.

## Go step by step

`hmp.Lab("project.toml")` builds nothing. `hmp.Lab(hmp.open("runs/my_run"))` opens the project of a run with the configuration the run kept, sealed or stopped after its facts, and builds nothing either. `lab.advance` then builds the model of that run again in memory, because a run stores results and not its model. `lab.set` starts from the configuration of the run, and `lab.run` writes a new run in the same project. `lab.advance()` plays the next step and `lab.advance("build_mesh")` plays every missing step up to that one. `lab.steps` is a table with one row per step, with its status (`built`, `stale` or `pending`), its last duration in seconds, the sections of the configuration it reads and the objects forced on it.

`lab.state` holds nine objects by name: `config`, `geographic`, `domain`, `flow`, `data`, `mesh`, `model`, `plan` and `solves`. Before its step plays, `geographic`, `domain`, `flow`, `mesh`, `model` and `plan` are `None`. After a change, a stale object stays in the state until its step plays again. Reading `lab.state` computes nothing. `lab.solve()` plays up to `run_solver` and gives one solved run per run of the plan.

## Build the configuration section after section

`hmp.Lab({"geographic": {...}, "data": {...}}, base="my_project")` reads the dict as `hmp.Project(dict)` does, with the same refusals and the same old key names. When a run would lack content, such as `[simulation]`, the lab keeps the dict as a draft. `lab.set` adds the other sections when you need them, such as `lab.set(domain={...})` before `build_mesh` and `lab.set(flow={...}, simulation={...})` before `run_solver`. In a draft every `lab.set` reads the configuration again and plays the steps again from the start, so the data plan, the types of data and the solver always follow what is written. `lab.advance` refuses to play a step that reads a section the draft lacks, and names the step and the section. Today that is `[simulation]`, which `setup_process` reads to plan the runs. `lab.run` and `lab.write_config` refuse while the draft lacks what `hmp run` asks of a file, and list it, for example a real catchment without `[site]`. No run starts from a draft, so `lab.project.simulate()` refuses it too. Once the configuration is complete the lab works as a lab of a file, and a path that no step reads is refused.

## Change a value

`lab.set(K=5e-5)` changes the configuration of the lab. A key is a short name of `hmp config targets`, a dotted path of the TOML such as `flow.param.K.field.value`, or a whole section such as `data={...}`. The new configuration is checked at once, and when your changes bring the configuration back to the file, the lab forgets them, so a run seals none. `lab.set` returns the built steps that became stale, and `lab.steps` shows them. The next `advance` plays again from the first of them. `lab.config` is a frozen copy of the configuration with your changes.

## Force an object

Some objects cannot be said in the configuration, for example a mesh you built by hand. `lab.force("mesh", my_mesh)` puts it in the state. The lab keeps it each time its step plays, and the steps after it become stale. `lab.force` accepts `geographic`, `domain`, `flow`, `data`, `mesh` and `model`. `lab.release("mesh")` forgets the value, and the step builds the object again. While an object is forced, `lab.set` warns that this object does not follow the change.

## Look inside a function

`lab.capture` records the local variables and the returned value of the functions you name, each time one returns. A target is `"path/file.py:function"` or `"path/file.py:Class.method"`, and the file is matched by the end of its path. The block gives a dict from each target to the list of its calls. The hook slows the solve by about a factor of two, so name few targets.

## Keep the result

`lab.run("name")` seals the model of the lab as a run of the project, as `Project.simulate` does, and gives the run back. When `run_solver` is built and up to date, the run takes the solve of the lab and does not solve again, so its seal, its stored heads and its `profile.json` are those of `hmp.run` with the same changes. It uses the configuration of the lab, so it refuses to start while an object is forced. Release the object, or say the change with `lab.set`. A run made from a reopened run records its changes against the configuration of that run, whose `config.toml` is complete, so the new run replays. A project that keeps solver files solves again at `lab.run`, because the export keeps only the files of the run itself. The run cleans the solver files, so after it the steps from `prepare_solver` on are stale in the lab.

`lab.write_config("project_tuned.toml")` writes the configuration of the lab, with its changes, as a TOML file you can run with `hmp run`. `lab.close()` removes the scratch folder of the lab, and `with hmp.Lab(...) as lab:` does it for you.

## An example

The lines below come from a test that runs on every change.

```{literalinclude} /../../tests/unit/project/test_lab.py
:start-after: "# [lab-walkthrough]"
:end-before: "# [/lab-walkthrough]"
:dedent: 4
:language: python
```

## Limits

The lab plays in memory up to `run_solver`. The steps after it belong to a run, so `lab.advance` refuses them and names `lab.run`. `lab.solve(build_only=True)` builds each flow run without solving it, and a later `lab.solve(built)` solves these runs. That route plays no transport run. Two labs on one project work in separate scratch folders, so they do not disturb each other.
