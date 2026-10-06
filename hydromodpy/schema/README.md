# `hydromodpy/schema`

The contracts that something outside the Python code relies on. Two kinds.
The first is for a front end: the JSON Schema of the whole configuration and a
validator for one field at a time, so a form can check a value without loading
a project. The second is for an orchestrator: the job directory a capability is
invoked through as an external process, the declaration of each capability, its
generated description, and the licence of each data source.
This file is the map of the package: what each part answers, the import
rules, how a job directory is written, and where to add what.

## Parts

| part | answers |
|---|---|
| `export.py` | `export_full_schema(dir)` writes three files: `config.json` (the JSON Schema of `HydroModPyConfig`), `config_meta.json` (ordered root sections, groups, which sections are repeated tables) and `field_validators.json` (field path to validator type) |
| `partial_validator.py` | `validate_field(path, value)`: the type of one field of `HydroModPyConfig`, checked on its own, with a `ValidationResult` |
| `capability.py` | `CapabilityDecl` and `OutputDecl`: what a capability declares about itself before it runs. Standard library only |
| `processes/` | the machine-readable description of each capability this build serves (`<id>@<major>.json`) and `index.json`, read as package data |
| `job/` | the job directory contract: layout and write order, `JobDirectory`, the request, the input set, the provenance, the outcome, the seal, reuse, and chains of capabilities |
| `media_types.py`, `generated_views.py` | the media types a job document names and the file names of the generated views (RO-Crate, STAC, PROV), each spelled once |
| `sources.py` | the licence of each data source this build reads, the sidecar a user file may carry, and how licences roll up |
| `site_selection_manifest.py` | the manifest of a site-selection run: names, required keys, and the checks of each output file |

`job/` in short:

| module | answers |
|---|---|
| `layout.py` | the names inside a job directory and the order they are written in (`JOB_WRITE_ORDER`, `ALLOWED_JOB_ENTRIES`) |
| `directory.py` | `JobDirectory`: resolves its root once, so that an input path is checked to stay inside it; a URI scheme other than `file:` is refused |
| `request.py`, `refusal.py` | the input document, read and refused in one typed shape; `content_address()` gives the `job_id`; how a member of a request is refused |
| `inputset.py`, `extent.py` | what the job consumed, hashed and annotated with a licence; the one box-and-CRS shape a job records a place in |
| `provenance.py`, `outcome.py` | how the job ran, with no instant and no host name; the typed status, which refuses to contradict its exit code |
| `seal.py`, `reuse.py` | `seal_job` and `verify_job`; what a sealed directory is answered with when the same job comes again |
| `chain.py` | running several capabilities in a row, each filling its inputs from the artefacts of an earlier one; it knows no capability |
| `documents.py`, `digest.py` | atomic document writes, the two digests |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives schema `core`, `config` and
itself. Today it imports `core`, and `config` at two places only:
`export.py` (the raw schema of `config.schema_export`) and `partial_validator.py`
(inside a function). No `schema_layout.yaml` orders the parts. Three rules hold:

1. `job/` and `capability.py` stay readable by a layer that owns no engine.
   `capability.py` carries the request model as an opaque type, and `job/chain.py`
   takes the registry that pairs a declaration with a body as an argument,
   because that registry lives in `cli`.
2. A capability is declared next to the code that serves it, not here:
   `data/request/job.py` (`DATA_REQUEST`),
   `spatial/domain/capability.py` (`DOMAIN_BUILD`) and
   `spatial/site_selection/hydrology/capability.py` (`TERRAIN_DELINEATE`).
   `cli/_workers/process.py` pairs each declaration with its body.
3. The schema export stays deterministic: no side effect, no field that
   depends on the environment.

Who imports schema: `spatial` (job documents, site-selection manifest),
`data` (job documents, sources), `results` (sources, media types, generated
views), `cli`, `reporting` and `analysis`.

## Tree

```
hydromodpy/schema/
  __init__.py       export_full_schema, validate_field, ValidationResult
  export.py  partial_validator.py
  capability.py  media_types.py  generated_views.py  sources.py  site_selection_manifest.py
  processes/        index.json  <id>@<major>.json   (generated)
  job/              layout.py  directory.py  request.py  inputset.py  extent.py
                    provenance.py  outcome.py  seal.py  reuse.py  chain.py
                    documents.py  digest.py  refusal.py
```

## The two ways in

For a front end, from a terminal or from Python:

```
hmp dev schema export --output ./schema/
hmp dev schema validate-field <path> <value> [--context FILE]
```

There is no HTTP server. A consumer ships the JSON over its own transport.
`validate_field` takes `context` and `locale` and does not use them yet.
Per-field annotations come from `json_schema_extra` of the Pydantic models;
the keys a model may use are listed in `core/config_kit/field_metadata.py`.

For an orchestrator:

```
hmp process list
hmp process describe <id>
hmp process run <id> --job DIR
hmp process chain --root DIR
hmp process verify --job DIR
```

## How a job directory is written

The caller creates the directory and writes `request.json`. The process then
writes, in this order: `outputs/`, `inputset.json`, `provenance.json`,
`outcome.json` and `manifest.json`. `logs/` and `progress.ndjson` are not
artefacts and are not in the seal. The invariant that the order buys:
`manifest.json` exists if and only if the job succeeded and every declared
output is present and hashed. A caller outside the process never has to guess.

`seal_job` writes the manifest last and atomically; `verify_job` re-checks a
directory against it from the disk alone. A directory that already holds the
same `job_id` is re-reported with `reused` set and nothing is written
(`reuse.py`); a different one is refused. A generated view (RO-Crate, STAC,
PROV) may be added after the seal and is not inventoried by it.

## Where to add what

| to add | where |
|---|---|
| a capability | a `CapabilityDecl` and its body in the layer that owns the logic, a registry entry in `cli/_workers/process.py`, then regenerate the description with `python -m tools.processes` |
| a field annotation | a key in `core/config_kit/field_metadata.py`, then use it in the model; see `docs/source/contribute/architecture/how-to/add-a-config-field.rst` |
| a validator type for a front end | `_infer_validator_type` in `export.py` |
| a data source licence | an entry in `_ENTRIES` of `sources.py`, with the basis for it; a source whose licence is not known says so with `_undetermined` |
| a media type | a constant in `media_types.py`, used by the declaration, the outcome and the seal alike |
| a generated view | a file name in `generated_views.py` |
| a job document | a module in `job/`, its place in `layout.py` and in the seal |
