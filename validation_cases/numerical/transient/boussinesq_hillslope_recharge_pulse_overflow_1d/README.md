# Boussinesq Hillslope Recharge Pulse Overflow 1D

Numerical transient stress case dedicated to surface interaction on a sloping
hillslope. The goal is not an analytical benchmark; it is a controlled overflow
scenario for comparing:

- `petsc_partition`: PETSc with the regularized partition law,
- `petsc`: PETSc with complementarity,
- `boussinesq` / `scipy_sparse`: regularized-partition references on the
  existing non-PETSc paths.

The case is intentionally stored under `validation_cases/numerical/` so it does
not get mixed into the analytical batch inventory.

Scenario:

- `400 m` long strip with linear topography,
- only one fixed head on the downstream east side,
- transient recharge pulses of increasing intensity,
- low downstream head so overflow appears and recedes during the sequence.

The runner produces one composite figure with:

- selected mean head profiles,
- a time-space heatmap of surface overflow,
- either a head-clearance heatmap or a solver-difference heatmap,
- recharge and integrated overflow time series,
- overflow front and active-length dynamics.
- optional GIF / HTML animation exports for the transient evolution.

For Linux / PETSc comparisons across several Boussinesq methods, the case also
ships a dedicated multi-solver runner that focuses on:

- one total-overflow overlay shared by all compared methods,
- one execution-time comparison figure,
- one `timeseries.csv` and one `execution_times.csv` for downstream analysis.

Useful forcing controls:

- `--forcing-preset strong` triggers overflow earlier and more strongly over a `40 day` run,
- `--forcing-preset extreme` pushes the case further with lower downstream head over a `40 day` run,
- `--forcing-preset alternating` builds repeated on/off overflow windows on a `20 day` run,
- `--forcing-scale <factor>` multiplies the recharge chronicle,
- `--east-head <m>` and `--initial-head <m>` let you tune the hydraulic support.

Direct execution:

```bash
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc_partition --show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc_partition --compare-solver petsc --show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc_partition --compare-solver scipy_sparse --snapshot-days 0 12 24 36 40 --no-show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc_partition --forcing-preset strong --gif --show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc --forcing-preset alternating --show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc_partition --forcing-preset strong --mp4 --frame-step 1 --video-fps 12 --show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_case --solver petsc_partition --forcing-preset strong --output-root /mnt/c/Users/dreuzy/Documents/HydroModPyOutputs --show
python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_multi_solver_case --solvers boussinesq petsc_partition petsc --forcing-preset strong --output-root /mnt/c/Users/dreuzy/Documents/HydroModPyOutputs/bouss_multi_linux
bash validation_cases/numerical/transient/boussinesq_hillslope_recharge_pulse_overflow_1d/run_multi_solver_case_linux.sh /mnt/c/Users/dreuzy/Documents/HydroModPyOutputs/bouss_multi_linux
```

Useful options:

- `--compare-solver <name>` overlays a second formulation,
- if the comparison solver fails, the primary run still completes and the error is printed instead of aborting the whole runner,
- `--snapshot-days ...` forces the profile snapshots,
- `--max-snapshots N` limits the top-panel clutter,
- `--overflow-threshold-mm-day X` changes the footprint activation threshold,
- the runtime summary now records activation-window counts and state transitions for repeated overflow on/off sequences,
- `--output-root /mnt/c/...` writes the validation workspace directly to a Windows-visible folder from WSL,
- `--gif` exports an animated GIF,
- `--mp4` exports an MP4 video in the same output directory,
- `--html-animation` exports a browser slider from the rendered frames,
- `--video-fps N` controls MP4 smoothness,
- `--frame-step N` subsamples the animation frames.
- `run_multi_solver_case` is the Linux-ready entrypoint when the goal is only the total-overflow overlay and execution-time comparison across several Boussinesq methods.
