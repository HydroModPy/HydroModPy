# `hydromodpy/schema`

The shapes HydroModPy writes for a reader outside this process. One family is for a front end,
the JSON Schema of the whole configuration and the sentence of each code a check gives. The
other is for an orchestrator, the job directory a capability writes and the declaration of each
capability. `seal.py` holds the one seal of a run and of a job, at `manifest_version` 4 with a
`profile`, and `lineage.py` the block both profiles carry. `results/record/manifest.py` extends
the seal for a run, because the blocks of a run are types of `results`. `changes.toml` is the
register of the numbers, defaults and keys that move, and `phrases.toml` the sentence of each
check code, label value, label reason, check state and line of the method text of a run, in
English and in French. `phrases.py` is its one reader. `processes/` holds the generated description of each capability and `results/` the
published JSON Schemas. The package reads `core` and itself, as
`tests/unit/architecture/layer_matrix.yaml` says. The answers column below is the first line of
each module docstring.

| module | answers |
|---|---|
| `capability.py` | What a capability declares about itself, before any of it runs. |
| `changes.py` | The register of changes, `changes.toml`, read once and checked. |
| `config_schema.py` | JSON Schema export of the HydroModPy configuration. |
| `generated_views.py` | The file names a generated view takes inside a run or a job directory. |
| `job/` | The job directory: what a capability is handed, and what it leaves behind. |
| `lineage.py` | The `lineage` block of a seal: where a run comes from, by ids. |
| `media_types.py` | The media types a job document names, spelled once. |
| `phrases.py` | The one reader of `phrases.toml`: the sentence of a code, in English and in French. |
| `seal.py` | The one seal of a run and of a job: what a finished directory promises. |
| `sources.py` | The licence and the facts of each data source this build reads, stated once. |
