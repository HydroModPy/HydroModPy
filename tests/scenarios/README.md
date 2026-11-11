# Scenarios

A scenario is a small synthetic project played once by the real pipeline.
There are twenty-eight, and their list is the `SCENARIOS` tuple of
`test_harness.py`. `factory.py` writes each project as TOML text, so a project
has the same bytes on every machine. The two lake projects of scenario 5 hold
binary rasters, so their text names a folder that the test fills or points at
`tests/data/sfr_cheze/`.
`launcher.py` plays a project in a child process under a throwaway HOME, state
and cache, with the solver binaries of the machine linked in.
`PLAYED_BY` in `test_harness.py` names the scenario of each solver, mesh
engine, terrain engine and export format, so a new backend without a scenario
fails the harness. A new scenario is a factory function, a file, and a line in
`SCENARIOS` and `PLAYED_BY`.
The twenty-eight run in under ten minutes with `pytest -n 8`. A scenario over
twenty seconds gets fewer steps or a smaller grid when its assertion allows it.
Coverage follows every child process through `patch = ["subprocess"]` in
`pyproject.toml`.
