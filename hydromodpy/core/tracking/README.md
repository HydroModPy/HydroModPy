# core/tracking

This folder answers: which files does a config read? The answer feeds the reproducibility manifest of
a run.

## Modules, in the order a caller uses them

1. `input_file.py` has the `InputFile` annotation that marks a config field as a file to track, and the `TrackedFileEntry` result type.
2. `walker.py` walks a Pydantic config tree and collects every path marked `InputFile` (`collect_input_files`). `rewrite_input_paths` rewrites those paths when a project moves.

## What other layers import from it

`data` (most), `spatial`, `workflow`, `results`, `project`, `model` and `config`.

## Where to add what

- A config field that points to a file: annotate it with `InputFile`, nothing else.
- A new fact kept about each file: `TrackedFileEntry` in `input_file.py`.

The layer rules are checked by `tests/unit/architecture/`.
