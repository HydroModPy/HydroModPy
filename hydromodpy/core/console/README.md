# core/console

This folder answers: what does a run show while it works? It holds the live progress display on the
terminal and a second sink that writes the same progress as lines of JSON.

## Modules, in the order a caller uses them

1. `progress.py` is the one progress system: phases with a checkmark, spinner statuses and progress bars on stderr (`phase`, `status`, `task`, `console`, `make_console_handler`, `set_console_mode`).
2. `ndjson.py` is the sink that does not depend on the terminal renderer. When the variable named by `ENV_VAR` is set, `emit` writes one JSON line per event, so a parent process can follow a child run.

## What other layers import from it

`data`, `solver`, `spatial`, `workflow`, `model`, `cli` and `calibration` import `progress`. The logging policy that decides when the display runs is in `hydromodpy/core/logging.py`.

## Where to add what

- A new kind of progress line: `progress.py`, and the matching event in `ndjson.py`.
- A new consumer of the progress events: read the NDJSON, do not add a second display.

The layer rules are checked by `tests/unit/architecture/`.
