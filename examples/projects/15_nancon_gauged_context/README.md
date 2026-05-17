# Nancon gauged context package

This project builds a pre-calibration context package for the gauged Nancon
case. It intentionally stops before calibration: the goal is to verify the
domain, observed discharge, recharge/runoff forcings, and hydrographic network
context.

Recommended sequence from the repository root:

```powershell
python -m hydromodpy run examples/projects/02_nancon_watershed/run_hydrographic_network_comparison.toml
python examples/projects/15_nancon_gauged_context/build_nancon_gauged_context.py
```

Main output:

```text
examples/projects/15_nancon_gauged_context/outputs/web/index.html
```

The context builder reuses the canonical Nancon base project under
`examples/projects/02_nancon_watershed` and the local example data under
`examples/data`.
