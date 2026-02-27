# Temporal

`hydromodpy/solver/utils/temporal/` contains time-discretization helpers.

- `tmesh_generation.py`: temporal mesh/grid generation class (`TMesh_Generation`)
  with typed config (`TMeshConfig`) and backward-compatible alias
  (`TGrid_Generation`).
- `tmesh_config.py`: Pydantic model (`TMeshConfigModel`) + TOML helpers for
  validating temporal-mesh inputs.
- `tmesh_config.toml`: template with all `TMesh_Generation` entries.
- `cases/`: runnable temporal demo cases (`run_tmesh_case.py`) and sample TOML
  (`run_tmesh_config.toml`).

