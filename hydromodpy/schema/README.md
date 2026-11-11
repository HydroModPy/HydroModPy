# schema

The shapes that HydroModPy writes for a reader outside this process. One family is for a front end, the JSON Schema of the whole configuration and the sentence of each code that a check gives. The other is for an orchestrator, the job directory that a capability writes and the declaration of each capability. The package reads `core` and itself, so a document can be described without importing any science.

`seal.py` holds the one seal of a run and of a job, at `manifest_version` 4 with a `profile`, and `lineage.py` holds the block that both profiles carry. `changes.toml` is the register of the numbers, defaults and keys that move, and `phrases.toml` gives the sentence of each check code, label value, label reason, check state and line of the method text of a run, in English and in French. `phrases.py` is its one reader.

`job/` has the job directory, `processes/` the generated description of each capability and `results/` the published JSON Schemas of the stored formats.

The page of the package in the developer docs lists the modules with the first line of their docstring and tells how the folders fit together.
