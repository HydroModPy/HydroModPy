# Boussinesq Hillslope Sloping-Substratum 1D

Transient numerical example dedicated to one specific question:

- does `flow/boussinesq` respond coherently when the **substratum itself is sloping**, not only the surface topography?

This example is intentionally separate from the overflow benchmark used in the
cross-solver comparisons. It is meant to isolate the effect of `z_bottom(x)`
without mixing it with the already existing test setup.

Scenario:

- `400 m` long strip,
- linear topography decreasing toward the outlet,
- **independent sloping substratum** so aquifer thickness varies along the hillslope,
- east fixed head,
- west divide,
- transient recharge pulse followed by recession.

Implementation note:

`Boussinesq` does support substratum slope because the runtime uses the per-cell
`z_bottom` values from the mesh bundle to compute saturated thickness and
surface interaction.

Runner:

```bash
python -m validation_cases.numerical.transient.boussinesq_hillslope_sloping_substratum_1d.run_case --output-root out/boussinesq_hillslope_sloping_substratum_1d
```

This case was **not executed in this session**.
