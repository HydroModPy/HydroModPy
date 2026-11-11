# core/config_kit

This folder answers: what do all config models share? Every config class of every layer inherits
from the base here, so the strictness and the visibility rules are written once.

## Modules, in the order a caller uses them

1. `base.py` is `HydroModelBase` (`extra="forbid"`, `validate_assignment=True`), the parent of every config model.
2. `profile.py` and `visible_when.py` are the `Profile` enum (`USER`, `DEV`, `EXPERT`) and the `VisibleWhen` tag that decide which field shows in which profile.
3. `introspect.py` reads that metadata off a field; `field_metadata.py` fixes how `json_schema_extra` is written.
4. `types.py` has the shared constrained types and `Literal` aliases.
5. `calibrable.py` is the marker of a calibrable field. It lives here so `model` and `calibration` need not import each other.
6. `persistence.py` is the one save or no-save switch of every write path.
7. `written.py` tells what a config was given, as opposed to the defaults it took (the frozen config of a run).
8. `said.py` is where a validator says its warnings. `say` warns as usual, and inside `collecting()` it keeps the text for the caller, so a check collects them per thread and never touches the warning filters of the process.
9. `stored.py` reads a stored document, which may come from a later 2.x.
10. `dump.py` writes a model as a commented TOML document (`dump_toml_with_comments`), the code behind `HydroModelBase.to_toml`.
11. `root.py` is `RootConfig`, the root model class and its two migrations held together. Every helper that reads sections or migrates a file receives it as its `root` argument, which is how core reaches the root config without importing `config`. `registry.py` walks that argument (`root_sections`, `repeated_root_sections`, `root_scalar_fields`) and keeps no module cache.
12. `field_param/` is the schema of a field-parameter TOML payload (`sections.py`, `units.py`, and `config.py` that resolves it). It lives here because `model/properties/` builds the field from it and `model/flow_config.py` embeds it in `[flow.param.<id>]`.

The `[[export]]` request moved to `hydromodpy/results/exporters/export_spec.py`.

## What other layers import from it

Every layer: `data`, `catchment`, `results`, `model`, `config`, `calibration` and `solver` first.

## Where to add what

- A field visibility rule: `profile.py` and `introspect.py`.
- A shared type: `types.py`.
- A section that must be listed at the root: the root model, never this folder.

The layer rules are checked by `tests/unit/architecture/`.
