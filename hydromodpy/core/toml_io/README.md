# core/toml_io

This folder answers: how is a TOML config read, merged and written back? Every config layer goes
through it, and it can point a validation error at the line of the file.

## Modules, in the order a caller uses them

1. `loader.py` reads a file with `base_config` inheritance (`load_toml_with_base_config`) and fixes the base of relative paths.
2. `merge.py` merges payloads: tables merge key by key, any other value, a list included, replaces the base.
3. `overrides.py` applies `--set key=value` and `HMP_SET_<key>` to the document.
4. `paths.py` resolves the file paths a config declares (`resolve_declared_path`) and parses dotted key paths.
5. `error_locator.py` maps a Pydantic error back to a TOML line.
6. `generator.py` writes the commented template from the models (`generate_toml`), using `dynamic_examples_protocol.py` for the examples that `physics` and `spatial` provide. It reads the shapes of the models through `model_types.py`, writes one table with `section.py` and formats keys, values and comments with `render.py`.
7. `writer.py` renders a plain mapping (`dumps`, `dump`). A model with comments is written by `config_kit/dump.py`.

## What other layers import from it

`config`, `project`, `cli`, `workflow`, `calibration`, `schema` and `spatial`.

## Where to add what

- A new merge or override rule: `merge.py` or `overrides.py`, with a test of the round trip.
- A path key: `paths.py`.
- An example the template shows: in the owning layer, wired through the protocol.

The layer rules are checked by `tests/unit/architecture/`.
