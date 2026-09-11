# Transport MF6 GWT DISV Visual Guard

This example is a visual non-regression bench for MODFLOW 6 GWT transport on
small triangular DISV meshes.

It is intentionally separate from `10_testbed_workflow`: the goal is not a large
natural campaign, but a controlled transport workbench that makes each step easy
to inspect before refactoring the production transport code.

## What It Produces

For each case, the runner writes:

- `index.html` with the configuration, key parameters, figures and signatures;
- `figures/domain_context.png`;
- `figures/mesh_overview.png`;
- `figures/hydraulic_conductivity.png`;
- `figures/head_final.png`;
- `figures/flux_proxy.png`;
- `figures/cell_peclet.png`;
- `figures/concentration_snapshots.png`;
- `figures/concentration_profiles.png`;
- `figures/probe_breakthrough.png`;
- `figures/plume_evolution.png`;
- `figures/analytical_profile_comparison.png` for cases with a closed-form
  reference;
- `figures/analytical_error_diagnostics.png` for cases with a closed-form
  reference;
- `signatures.json`;
- `signatures.csv`.

The default mode is deterministic and synthetic. It does not require the `mf6`
executable, so it can run in unit tests and during refactor preparation. The
optional `mf6` mode builds and runs a direct FloPy GWF+GWT DISV model using the
same mesh and case definition.

## Cases

- `case_01_homogeneous_k_pulse`: fine lightly perturbed triangular DISV mesh,
  homogeneous K and a compact internal pulse.
- `case_02_longitudinal_channel_kx5_pulse`: high-K longitudinal channel aligned
  with mesh rows.
- `case_03_transverse_bands_kx5_pulse`: alternating transverse K bands aligned
  with mesh columns.
- `case_04_random_blocks_kx5_pulse`: deterministic blocky random K aligned with
  coarse mesh blocks.

All cases use the same diffusion coefficient. In heterogeneous cases, the cell
Peclet number varies because K varies by up to a factor of five.

The homogeneous internal-pulse case also includes a closed-form 2D infinite-domain
Gaussian advection-diffusion reference. Heterogeneous K cases do not use an
analytical comparison because the uniform-velocity assumption no longer holds.

## Usage

Generate the synthetic visual guard:

```powershell
python examples/projects/13_transport_mf6_gwt_disv_visual_guard/run_visual_guard.py
```

Generate only one case:

```powershell
python examples/projects/13_transport_mf6_gwt_disv_visual_guard/run_visual_guard.py --case case_01_homogeneous_k_pulse
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

The synthetic cases deliberately use a homogeneous-case pore velocity of about
`0.1 m/day`, a domain length of `120 m`, fine `96 x 24` triangular grids
(`4608` cells), and `61` output times. The homogeneous case targets a mean cell
Peclet number near `20`; heterogeneous cases keep the same diffusion coefficient
and let the Peclet number vary with K.
