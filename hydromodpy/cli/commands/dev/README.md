# `hydromodpy/cli/commands/dev`

`hmp dev` holds the commands a contributor uses on a checkout. They are out of
the contract: their options and their output may change without notice. What a
user needs lives at the top level (`hmp completion`, `hmp lock`,
`hmp catalog rank`, `hmp config schema`).

| module | command |
|---|---|
| `run_script.py` | `hmp dev run-script FILE`: run a Python prototype with the banner, outside `hmp run` |
| `examples.py` | `hmp dev examples manifest`: write `hydromodpy/examples/catalog.toml` again from the checkout |
| `manage/` | `hmp dev manage`: a local web page to look through the index tables of a workspace and remove runs. `backend.py` reads and writes, `static/index.html` is the page |
| `test.py` | `hmp dev test`: run the unit, regression or validation tests of this checkout in a scratch folder outside it (`HMP_TEST_SCRATCH_ROOT`) |
