# `hydromodpy/schema`

The contracts that something outside the Python code relies on. Two kinds.
The first is for a front end: the JSON Schema of the whole configuration and the
sentence of each code a check of a document gives, in English and in French, so a
form can show what is wrong without loading a project. The second is for an
orchestrator: the job directory a capability
writes, the declaration of each capability, its generated description, and the
licence of each data source.
This file is the map of the package: what each part answers, the import
rules, and where to add what.

## Parts

| part | answers |
|---|---|
| `config_schema.py` | the JSON Schema of the configuration: `export_schema(model_cls, ...)` (the root, a section or a model, filtered by profile, with its `urn:` identity), `editor_schema(model_cls)` (what an editor checks one TOML file against), `schema_sha256(model_cls)` (the fingerprint the lockfile records), and `export_full_schema(dir, root=model_cls)`, which writes three files for a front end: `config.json`, `config_meta.json` (ordered root sections, groups, which sections are repeated tables) and `field_validators.json` (field path to validator type) |
| `phrases.toml` | the sentence of each code a check gives. The table `[check.<code>]` holds `en` and `fr`. `config/check.py` reads it through `phrase(code, lang)`, so a command line, a server and a form write the same words |
| `capability.py` | `CapabilityDecl` and `OutputDecl`: what a capability declares about itself before it runs. Standard library only |
| `processes/` | the machine-readable description of each capability this build serves (`<id>@<major>.json`) and `index.json`, read as package data |
| `job/` | the job directory contract: layout and write order, `JobDirectory`, the request, the input set, the provenance, the outcome, the seal and reuse. See `job/README.md` |
| `media_types.py`, `generated_views.py` | the media types a job document names and the file names of the generated views (RO-Crate, STAC, PROV), each spelled once |
| `sources.py` | the licence of each data source this build reads, the sidecar a user file may carry, and how licences roll up |
| `changes.toml` | the register of changes: each bug fix, each rule that moves a number, each default that moves with an edition and each key that moves, one row each, read as package data |
| `changes.py` | the one reader of the register. `REGISTER` is read once at import, and a faulty row stops the import. It also holds `migrations_of(document)`, `editions()`, the delay of two minor versions (`outlived`) and the sentence that refuses a form of a pre-release |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives schema `core` and itself, and
nothing else. `config_schema.py` walks the root model
it receives as its `model_cls` argument, so it never imports
`config`. No `schema_layout.yaml` orders the parts. Three rules hold:

1. `job/` and `capability.py` stay readable by a layer that owns no engine.
   `capability.py` carries the request model as an opaque type, so it names no engine.
2. A capability is declared next to the code that serves it, not here:
   `data/request/job.py` (`DATA_REQUEST`),
   and `model/domain/capability.py` (`DOMAIN_BUILD`).
3. The schema export stays deterministic: no side effect, no field that
   depends on the environment.

Who imports schema: `catchment` (job documents, capability declaration, media
types), `data` (job documents, sources), `results` (sources, media types, generated
views), `display`, `workflow`, `project` (the lockfile fingerprint) and `cli`.
The register is read by `config` (the migration and `edition`), `results` (the label
of a run reads its bugs), `data` (the sidecar rows), and `model`, `solver` and
`calibration` (the sentence that refuses a key of a pre-release).

## Tree

```
hydromodpy/schema/
  __init__.py       the docstring of the package, no name
  config_schema.py  phrases.toml
  capability.py  media_types.py  generated_views.py  sources.py
  changes.py  changes.toml
  processes/        index.json  <id>@<major>.json   (generated)
  job/              layout.py  directory.py  request.py  inputset.py  extent.py
                    provenance.py  outcome.py  seal.py  reuse.py
                    documents.py  digest.py  refusal.py  worker.py
```

## The two ways in

For a front end, from a terminal or from Python:

```
hmp config schema --bundle --to ./schema/
hmp config check --partial --format json <file>
```

There is no HTTP server. A consumer ships the JSON over its own transport.
The check of a document, `check(document, partial=True)`, lives in `config/check.py`
because it needs the root model. It reads the sentence of each code here, in
`phrases.toml`, and a key that a form has not filled yet comes back as `to_fill`.
Per-field annotations come from `json_schema_extra` of the Pydantic models;
the keys a model may use are listed in `core/config_kit/field_metadata.py`.

For an orchestrator, the contract is the job directory of `job/README.md`. A
capability is a function `run(job, *, exit_code_for)` in the layer that owns the
logic; no `hmp` verb starts one.

## Where to add what

| to add | where |
|---|---|
| a capability | a `CapabilityDecl` and its body in the layer that owns the logic, then regenerate the description with `python -m tools.processes` |
| a field annotation | a key in `core/config_kit/field_metadata.py`, then use it in the model; see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a validator type for a front end | `_infer_validator_type` in `config_schema.py` |
| a data source licence | an entry in `_ENTRIES` of `sources.py`, with the basis for it; a source whose licence is not known says so with `_undetermined` |
| a media type | a constant in `media_types.py`, used by the declaration, the outcome and the seal alike |
| a generated view | a file name in `generated_views.py` |
| a job document | a module in `job/`, its place in `layout.py` and in the seal |
| a number that moves, a default, a rule or a key that moves | one row of `changes.toml`, then `python -m tools.changes_changelog --write` for the `Numbers` block of `CHANGELOG.md`. `tests/unit/architecture/test_changes_register.py` holds the rest |
