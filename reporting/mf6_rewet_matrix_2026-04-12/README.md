# MF6 Rewet Diagnostic Matrix (2026-04-12)

Small DISV diagnostic matrix built from the committed `example12` triangular MF6 case.

Purpose:
- remove ocean forcing and wells;
- keep recharge strictly non-negative;
- set `negative_to_evt = false`;
- isolate whether MF6 `rewet` issues persist without `EVT`.

## Base case

- Base config: `examples/projects/launcher_simulation/run_demonstrative_annual_moderate_mf6_precomputed_mesh_input.toml`
- Mesh: committed `example12` triangular mesh
- Recharge: synthetic monthly series, all values non-negative
- Active sinks/sources: recharge only

## Matrix

| Case | IC | Drainage | Rewet | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| `ex12_top_rewet_off` | `top` | on | off | converged | usable physical heads |
| `ex12_top_rewet_on` | `top` | on | on | failed | divergence at stress period 8, time step 1 |
| `ex12_lowic_rewet_off` | `1.0 m` | on | off | converged | final state fully non-physical / dry collapse |
| `ex12_lowic_rewet_on` | `1.0 m` | on | on | converged | identical final state to `rewet_off` |
| `ex12_lowic_rewet_off_drain_off` | `1.0 m` | off | off | converged | identical final state to drainage-on low-IC runs |
| `ex12_lowic_rewet_on_drain_off` | `1.0 m` | off | on | converged | identical final state to drainage-on low-IC runs |
| `ex12_top_rewet_off_drain_off` | `top` | off | off | failed | divergence at stress period 1, time step 1 |
| `ex12_top_rewet_on_drain_off` | `top` | off | on | failed | divergence at stress period 1, time step 1 |

## Strong conclusions

1. `EVT` is not the source of the rewet issue on this reduced case.
   - Recharge is always non-negative.
   - `negative_to_evt = false` in all matrix overlays.
   - The `top + drainage on` branch still separates `rewet=false` (passes) from `rewet=true` (fails).

2. The cleanest discriminator is:
   - `ex12_top_rewet_off.toml`: converges
   - `ex12_top_rewet_on.toml`: fails at SP8/TS1

3. The `drain off` branch is not a good minimal control.
   - Even `rewet=false` fails from `top` initial conditions at SP1/TS1.
   - That branch is therefore not isolating `rewet`; it is a different ill-conditioned setup.

4. The `low IC = 1.0 m` branch is also not a good rewet discriminator.
   - All four low-IC variants converge to the same collapsed dry state.
   - Final MF6 heads contain no finite physical values in the head file after filtering dry/sentinel values.

## Useful files

### Configs

- `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_off.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_on.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_lowic_rewet_off.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_lowic_rewet_on.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_lowic_rewet_off_drain_off.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_lowic_rewet_on_drain_off.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_off_drain_off.toml`
- `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_on_drain_off.toml`

### Key diagnostics

- Passing reference:
  - `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_off/results_simulations/mf6_ex12_top_rewet_off/mfsim.lst`
- Rewet failure without EVT:
  - `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_on/results_simulations/mf6_ex12_top_rewet_on/mfsim.lst`
- Console capture for the rewet failure:
  - `reporting/mf6_rewet_matrix_2026-04-12/ex12_top_rewet_on.console.txt`
- Low-IC collapsed dry states:
  - `reporting/mf6_rewet_matrix_2026-04-12/ex12_lowic_rewet_on/results_simulations/mf6_ex12_lowic_rewet_on/mf6_ex12_lowic_rewet_on.hds`
  - `reporting/mf6_rewet_matrix_2026-04-12/ex12_lowic_rewet_off/results_simulations/mf6_ex12_lowic_rewet_off/mf6_ex12_lowic_rewet_off.hds`

## Interpretation

At this point the evidence is:
- `rewet` is not an `EVT` artifact;
- MF6 wetting/drying remains fragile on a smaller DISV case;
- but the fragility is path-dependent, not universal:
  - one physically reasonable branch fails only when `rewet=true`,
  - another branch converges regardless of `rewet` because the model collapses to a dry state.

That makes the next useful target narrow:
- keep `top` initial conditions,
- keep drainage on,
- keep recharge non-negative,
- vary only `rewet_record` parameters (`wetfct`, `iwetit`, `ihdwet`, `wetdry`).

## Quick tuning sweep on the discriminant branch

Additional overlays tested on the same branch (`top` IC, drainage on, recharge only, no EVT):

| Case | Changes vs default rewet | Result |
| --- | --- | --- |
| `ex12_top_rewet_on_wetdry001` | `mf6_rewet_wetdry = 0.01` | failed at SP8/TS1 |
| `ex12_top_rewet_on_wetfct05` | `mf6_rewet_wetfct = 0.5` | failed at SP8/TS1 |
| `ex12_top_rewet_on_ihdwet1` | `mf6_rewet_ihdwet = 1` | failed at SP8/TS1 |
| `ex12_top_rewet_on_combo` | `wetdry=0.01`, `wetfct=0.5`, `ihdwet=1` | failed at SP8/TS1 |

Interpretation:
- the failure is not removed by a small parameter retuning of the current NPF rewet settings;
- on this reduced case, the issue looks structural rather than a bad default `rewet_record`.
