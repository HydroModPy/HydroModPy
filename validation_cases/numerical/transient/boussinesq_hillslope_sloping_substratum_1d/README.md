# Boussinesq Hillslope Sloping-Substratum 10deg 1D

Transient numerical example dedicated to one specific question:

- does `flow/boussinesq` respond coherently when the **substratum itself is sloping**, not only the surface topography?

This example is intentionally separate from the overflow benchmark used in the
cross-solver comparisons. It is meant to isolate the effect of `z_bottom(x)`
without mixing it with the already existing test setup.

Scenario:

- `100 m` long strip,
- linear topography decreasing toward the outlet,
- **substratum inclined at `10 deg`**,
- topography inclined slightly more steeply so aquifer thickness stays positive,
- east fixed head,
- west divide,
- transient recharge pulse followed by recession.

Implementation note:

`Boussinesq` does support substratum slope because the runtime uses the per-cell
`z_bottom` values from the mesh bundle to compute saturated thickness and
surface interaction.

Current geometric convention:

- topography slope: `12 deg`
- substratum slope: `10 deg`

Runner:

```bash
python -m validation_cases.numerical.transient.boussinesq_hillslope_sloping_substratum_1d.run_case --output-root out/boussinesq_hillslope_sloping_substratum_10deg_1d
```

This case was **not executed in this session**.
