# Extensive Solver Intercomparison Regressions

This directory is reserved for solver-to-solver non-regression checks that are
too expensive for `tests/regression/fast/intercomparison/`.

Use this tier for cases that need larger meshes, longer transients, natural
catchment setups, or multi-solver matrices. These tests should still compare
compact numerical signatures, not full solver workspaces or generated figures.

Good candidates:

- MF6 structured vs MF6 irregular-triangle profiles on additional analytical
  validation cases.
- MF6 irregular-triangle vs Boussinesq on transient recharge or drainage
  scenarios.
- MF6 vs NWT on a shared structured benchmark where both backends are meant to
  represent the same physics.
- The full XT3D irregular-triangle method-choice matrix used by the capability
  gallery.

Currently committed:

- `test_boussinesq_natural_transient_intercomparison_extensive.py` relaunches
  the controlled 10 km2 natural transient recharge-pulse MF6/Boussinesq
  comparison and checks a compact metric signature. Its audit status may be
  `warn`, because known semantic warnings are intentionally kept visible.

Expected goldens live under
`tests/regression/reference/golden_references/extensive/intercomparison/`.

Run this tier explicitly:

```bash
python -m pytest tests/regression/extensive/intercomparison -q -n 1
python -m pytest -m "regression and extensive and intercomparison" -q -n 1
```
