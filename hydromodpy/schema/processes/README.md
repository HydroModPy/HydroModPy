# `hydromodpy/schema/processes`

The machine-readable description of each capability this build serves, read as
package data. `index.json` lists them, and each `<id>@<major>.json` describes one:
its inputs, taken from the JSON Schema of its request model, and its outputs.

The files are generated. `python -m tools.processes` writes them from the
`CapabilityDecl` of each capability, and a test refuses a committed file the
declaration no longer reproduces. `__init__.py` reads them (`read_description`,
`read_description_text`, `described_ids`) and imports no model.
