# Simulation Comparison Workflow Example

This example runs one external comparison experiment without changing the
simulation workflow. The comparison TOML generates two child simulation TOMLs
from one shared physical case, runs them through `hmp run`, then writes metrics,
audit files, reports, and figures.

Synthetic shared-mesh run:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case synthetic --show
```

Natural catchment run:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural --show
```

Reduced natural-mesh Boussinesq run:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural-bouss --show
```

Reduced natural-mesh Boussinesq run with recharge:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural-bouss-recharge --show
```

Reduced natural-mesh transient recharge-pulse run:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case natural-bouss-transient-pulse --show
```

Nancon transient seasonal recharge run:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case nancon-seasonal --show
```

Nancon transient seasonal recharge run with observed hydrography loaded:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case nancon-seasonal-hydrography --show
```

Nancon MF6-only hydraulic-conductivity sweep with observed hydrography loaded:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case nancon-seasonal-hydrography-k-sweep-mf6 --show
```

Run all examples:

```powershell
python examples/projects/09_comparison_workflow/run_comparison_example.py --case all --show
```

The same comparison TOMLs can also be executed through the public CLI:

```powershell
hmp run examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_vire_natural_mf6_nwt.toml
hmp run examples/projects/09_comparison_workflow/compare_10km2_natural_mesh_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_10km2_natural_mesh_recharge_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_nancon_transient_seasonal_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_nancon_transient_seasonal_hydrography_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_nancon_transient_seasonal_hydrography_k_sweep_mf6_only.toml
```

Synthetic outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/dupuit_mf6_vs_bouss
```

Natural outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/vire_natural_mf6_vs_nwt
```

Reduced natural-mesh Boussinesq outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/natural_mesh_10km2_mf6_vs_bouss
```

Reduced natural-mesh recharge outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/natural_mesh_10km2_recharge_mf6_vs_bouss
```

Reduced natural-mesh transient-pulse outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/natural_mesh_10km2_transient_pulse_mf6_vs_bouss
```

Nancon transient seasonal outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_mf6_vs_bouss
```

Nancon transient seasonal hydrography outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography_mf6_vs_bouss
```

Nancon MF6-only K-sweep outputs are written under:

```text
examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography_k_sweep_mf6_stable
```

Key files:

- `comparison_manifest.json`
- `comparison_report.md`
- `comparison_audit.md`
- `observables.csv`
- `comparison_metrics.csv`
- `comparison_differences.csv`
- `hydrographic_network_metrics.csv` when the compared runs expose both
  canonical hydrographic networks (`reference` and `generated`)
- `simulated_active_network_overlap_metrics.csv` when the runs expose
  `accumulation_flux`, a plottable mesh, and the observed `reference` network
- `comparison_figures/*.png`

Open `comparison_figures/case_configuration.png` first. It summarizes the
reference support used by the comparison: mesh geometry or cell centroids,
topography when available, detected fixed-head side boundaries, point/outlet
observables, and the recharge chronicle.

Then open the `*triptych*.png` figures. They show the reference head field, the
candidate head field, and the candidate-minus-reference difference in one panel.
