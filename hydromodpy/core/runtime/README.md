# core/runtime

This folder answers: how does the running process behave? It gives one call its bounds, declares the environment variables of an installation, and turns a termination signal into an exception.

## Modules, in the order a caller uses them

1. `bounds.py` is the bounds one call plays under. `Bounds` says which hosts a call may reach, under which roots it may read or write, and how many bytes and seconds a download may take. The class reads and writes no environment variable; callers build it from the command line or the server and pass it along.
2. `env.py` lists every `HMP_*` variable in one table (`ENV_VARS`, `EnvVar`, `env_var`) with its scope. It declares them and reads none.
3. `interrupts.py` makes SIGTERM raise like SIGINT (`terminate_as_interrupt`, `TerminationRequested`), so a long run closes its session in a `finally`.

## What other layers import from it

`calibration`, `data`, `project`, `results`, `workflow`, `cli`.

## Where to add what

- A bound on what one call may reach or take: a member of `Bounds` in `bounds.py`, and the check that applies it stays with the owner of the download or of the delivery.
- A new `HMP_*` variable: one entry in `env.py`.
- A new signal rule: `interrupts.py`.

A module of `core` never needs a higher layer: it receives what it needs as an argument. The bounds travel the same way, on the request or the environment object of the call.

The layer rules are checked by `tests/unit/architecture/`.
