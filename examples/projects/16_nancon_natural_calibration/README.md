# 16 - Natural network and discharge calibration

Scoring building blocks for calibrating against a natural target on the
Nancon catchment (EPSG:2154): compare a permanent drainage network against an
observed hydrographic network, and a simulated discharge series against an
observed one. `hydromodpy.calibration.observations.natural_observations`
provides the cost functions and the observation package writer; there is no
candidate-generation or optimizer loop yet, only scoring and reporting.

The network cost compares where simulated permanent drainage is active
against the observed network mask and its cell distances (`C_dist`). The
discharge cost is `1 - NSElog(Q_sim, Q_obs)`. The synthetic smoke test
combines both into `J = 0.3 * C_reseau_naturel + 0.7 * C_debit_obs`, a
placeholder weighting kept only so the smoke test runs end to end, not a
recommended objective.

## Run

```bash
# unit tests for the scoring module
python -m pytest -o addopts="" tests/unit/calibration/test_natural_observations.py -q

# HTML report reading a natural observation package
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_html_reporting.py::test_network_transient_html_uses_truth_mesh_when_reference_run_is_empty -q

# synthetic smoke test: 4 candidates, one HTML report, no real data needed
python examples/projects/16_nancon_natural_calibration/run_synthetic_natural_smoke.py --output-dir /tmp/hmp_nancon_natural_smoke

# build a natural observation package from arrays already projected on a mesh
python examples/projects/16_nancon_natural_calibration/build_observation_package.py \
  --network-mask-npz path/to/observed_network_active_mask.npz \
  --network-distance-npz path/to/observed_network_distance_by_cell.npz \
  --geometry-npz path/to/cell_geometry.npz \
  --mesh-bundle path/to/mesh_bundle

# real Nancon catchment report, wraps `hmp report catchment`
python examples/projects/16_nancon_natural_calibration/build_nancon_real_figures_report.py
```

Unit tests: 3.6 s (6 passed). Synthetic smoke test: 4.4 s. The real catchment
report replays a full overview and transient simulation of
`../02_nancon_watershed` and its duration is unmeasured here.

By default `build_observation_package.py` reads observed discharge from
`../15_nancon_gauged_context/outputs/context/observed_discharge_daily.csv`,
filtered to `2000-01-01..2002-12-31` and resampled to monthly (`ME`). Window,
frequency and warmup are CLI arguments.

## Data

| Source | Family | Role |
|---|---|---|
| `hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv` | hydrometry | observed discharge for `catchment_report.toml`, station `NANCON` |

`catchment_report.toml` also reuses the overview and transient run configs of
`../02_nancon_watershed` (`run_overview_all_apis.toml`, `run_transient_nwt.toml`);
`synthetic_natural_smoke.toml` is a placeholder path only checked for
existence by the reporting code, not a config that is ever loaded whole.

## What it shows

The synthetic smoke test scores four candidates on a 10-cell line mesh:

- `truth_identity`: matches the observation on both network and discharge,
  scores 0.
- `shifted_network`: correct discharge, shifted network, degrades
  `C_reseau_naturel` only.
- `high_discharge`: correct network, too much discharge, degrades
  `C_debit_obs` only.
- `combined_error`: degrades both terms.

What is still missing: automatic projection of the observed hydrographic
network onto a mesh, a driver that runs a steady/transient pair per candidate
parameter vector and calls `score_natural_network_transient_candidate`, and a
configurable objective composition instead of the fixed 0.3/0.7 weights.
