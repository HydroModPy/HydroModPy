# core/runtime

This folder answers: how does the running process behave? It gives one call its bounds, declares the environment variables of an installation, turns a termination signal or a stop request into an exception, and times a block.

## Modules, in the order a caller uses them

1. `bounds.py` is the bounds one call plays under. `Bounds` says which hosts a call may reach, under which roots it may read or write, and how many bytes and seconds a download may take. The class reads and writes no environment variable; callers build it from the command line or the server and pass it along.
2. `env.py` lists every `HMP_*` variable in one table (`ENV_VARS`, `EnvVar`, `env_var`) with its scope. It declares them and reads none.
3. `image.py` is the one reader of `HMP_IMAGE_TAG` and `HMP_IMAGE_DIGEST`. `image_of()` returns `{}` outside a container image, else the tag and, when the operator set it, the digest. A digest that is not `sha256:` and 64 hex characters raises `ConfigError`, which the server does when it starts. A run seals the result in `provenance.json` and calls `image_of(refuse=False)`, so a bad digest found late is sealed under `digest_refused` and does not stop the run.
4. `interrupts.py` makes SIGTERM raise like SIGINT (`terminate_as_interrupt`, `TerminationRequested`), so a long run closes its session in a `finally`. A stop can also come from a file. `raise_if_stop_requested(flag)` raises `StopRequested` when `<run or session>/.hmp/stop.json` exists, and does nothing for a flag of `None`. One check costs about two microseconds, so a loop may call it at every time step. `StopRequested` is a `KeyboardInterrupt`, so every block that closes a run on a signal closes it on a stop too.
5. `stopwatch.py` is the one stopwatch of a run. `measured(kind, name)` times a block with `perf_counter`, an exception included, and reads the peak memory of the process when the block ends. `process_age_s` gives the age of the process, which tells the start-up of a command from the time of its steps. The lines go to `profile.json`, written by `results/storage/run_profile.py`.

## What other layers import from it

`calibration`, `data`, `project`, `results`, `workflow`, `cli`.

## Where to add what

- A bound on what one call may reach or take: a member of `Bounds` in `bounds.py`, and the check that applies it stays with the owner of the download or of the delivery.
- A new `HMP_*` variable: one entry in `env.py`.
- A new signal rule, or a new place that reads the stop flag: `interrupts.py`. The writer of the flag is `request_stop` in `results/storage/attempt.py`.
- A new kind of timed block: its name in `MEASURE_KINDS` of `stopwatch.py`.

A module of `core` never needs a higher layer: it receives what it needs as an argument. The bounds travel the same way, on the request or the environment object of the call.

The layer rules are checked by `tests/unit/architecture/`.
