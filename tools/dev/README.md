# tools/dev

Three commands for someone who works on a checkout. They are not in the wheel, so a
user who installed HydroModPy never sees them. Run them from the root of the checkout
with `python -m tools.dev`.

| module | command |
|---|---|
| `test.py` | `test unit`, `test regression` or `test validation`: run that tier of `tests/` with a scratch folder outside the checkout (`HMP_TEST_SCRATCH_ROOT`) |
| `run_script.py` | `run-script FILE`: run a Python prototype from its own folder, after the banner |
| `examples.py` | `examples manifest`: write `hydromodpy/project/examples/catalog.toml` again from the checkout |

The old `hmp dev` group named the same commands. `hmp dev` still answers, with the line
that gives the new form, and `hmp dev manage` names the HTTP server,
`python -m hydromodpy_server --root ROOT`.
