# Transport MF6 GWT DISV Visual Guard

This example is a visual non-regression bench for MODFLOW 6 GWT transport on
small triangular DISV meshes.

It is intentionally separate from `10_testbed_workflow`: the goal is not a large
natural campaign, but a controlled transport workbench that makes each step easy
to inspect before refactoring the production transport code.

## What It Produces

For each case, the runner writes:

- `index.html` with the configuration, checks, figures and signatures;
- `figures/mesh_area.png`;
- `figures/head_final.png`;
- `figures/flux_proxy.png`;
- `figures/concentration_snapshots.png`;
- `figures/concentration_profiles.png`;
- `figures/mass_front.png`;
- `signatures.json`;
- `signatures.csv`.

The default mode is deterministic and synthetic. It does not require the `mf6`
executable, so it can run in unit tests and during refactor preparation. The
optional `mf6` mode builds and runs a direct FloPy GWF+GWT DISV model using the
same mesh and case definition.

## Cases

- `case_01_uniform_tri_constant_source`: uniform triangular mesh, constant
  upstream source.
- `case_02_perturbed_tri_constant_source`: same physics, lightly perturbed
  triangular mesh.
- `case_03_perturbed_tri_pulse`: pulse source, useful for checking temporal
  concentration mapping visually.
- `case_04_perturbed_tri_dispersion`: stronger dispersion, useful for checking
  front spreading.

## Usage

Generate the synthetic visual guard:

```powershell
python examples/projects/13_transport_mf6_gwt_disv_visual_guard/run_visual_guard.py
```

Generate only one case:

```powershell
python examples/projects/13_transport_mf6_gwt_disv_visual_guard/run_visual_guard.py --case case_03_perturbed_tri_pulse
```

Run the optional direct MF6/FloPy backend:

```powershell
python examples/projects/13_transport_mf6_gwt_disv_visual_guard/run_visual_guard.py --mode mf6
```

If `mf6` is not on `PATH`, pass it explicitly:

```powershell
python examples/projects/13_transport_mf6_gwt_disv_visual_guard/run_visual_guard.py --mode mf6 --mf6-exe C:\path\to\mf6.exe
```

Outputs are written under:

```text
examples/projects/13_transport_mf6_gwt_disv_visual_guard/outputs/
```

## Development Intent

Use this example before transport refactors to answer three questions quickly:

1. Is the DISV triangular mesh still what we expect?
2. Are the head and flow direction visually coherent?
3. Does the concentration front move and spread as expected?

The HTML report is for human inspection. The JSON/CSV signatures are for
non-regression tests. The committed synthetic baseline lives in
`reference/synthetic_signatures.json`; update it only after intentionally
changing the visual guard assumptions.
