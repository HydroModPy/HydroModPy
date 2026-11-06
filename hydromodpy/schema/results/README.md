# `hydromodpy/schema/results`

The JSON Schemas of the stored formats of `results`, as package data: one
`<name>.<version>.json` per document a run, a session, a plan or a publication
writes, and the one `hmp calibrate --format json` prints. A reader outside Python
validates a document against them without importing anything.

The files are generated from the Pydantic models with `model_json_schema()`.
`tests/unit/schema/test_results_schemas_match_models.py` refuses a committed file
the model no longer reproduces, and run as a script it writes them again.
`__init__.py` reads and writes the files and imports no model: the caller pairs a
file with its model, because `schema` has no edge towards `results`.
