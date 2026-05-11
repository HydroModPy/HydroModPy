# Nancon network physical benchmark

This example is a clean Nancon benchmark for comparing groundwater-release
diagnostics against the observed river network.

The purpose is to avoid mixing historical runs with different physical
settings. Every simulation starts from the same physical contract:

- same Nancon outlet and DEM;
- same monthly transient period, from 2020-10-01 to 2021-09-30;
- same monthly synthetic recharge values;
- same hydraulic parameters and aquifer thickness;
- same initial-condition rule: steady state under mean recharge.

The only intentional solver-specific physical difference is the surface
drainage conductance:

- MODFLOW 6 uses a high top drainage conductance: `1.0e-3 m2/s`;
- Boussinesq keeps the drainage conductance at zero: `0.0 m2/s`.

## Run

From the repository root:

```bash
python examples/projects/11_nancon_network_physical_benchmark/run_nancon_network_physical_benchmark.py
```

The script runs the comparison and writes the compact synthesis page:

```text
examples/projects/11_nancon_network_physical_benchmark/outputs/nancon_network_physical_benchmark/web_synthesis/index.html
```

To rebuild only the synthesis page from existing outputs:

```bash
python examples/projects/11_nancon_network_physical_benchmark/run_nancon_network_physical_benchmark.py --html-only
```

## What to compare

The generated page separates two questions:

1. Solver comparison on the same mesh:
   `mf6_disv_drain_high` vs `bouss_same_mesh_no_drain`.
2. MF6 mesh sensitivity at fixed physical settings:
   DISV reference, regular grids, and generated irregular meshes.

