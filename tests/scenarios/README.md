# Scenarios

A scenario is a small synthetic project played once by the real pipeline.
`factory.py` writes the island and its variants as TOML text. It reads no file
and no network, so a project has the same bytes on every machine.
`launcher.py` plays one scenario in a child process with `python -m hydromodpy`,
under a throwaway HOME, state and cache. The cache links the solver binaries of
the machine, and BLAS runs on one thread.
Each scenario test plays one scenario, so `pytest -n 6` spreads them over the
workers. The budget is ten minutes for about twenty-seven scenarios, and an
island takes about five seconds. A new scenario is a test that builds a
`Scenario` and calls `play`.
