# Calibration calage

Session `1c17c2c39cc54263a6aa64a447d7233e` of site `unnamed`, method `grid`, cost `rmse`, status **completed**.

- started 2026-11-03T05:21:51.395463+00:00, ended 2026-11-03T05:21:52.835213+00:00
- HydroModPy 2.0.0a5, configuration hash `38efa4990ac8acc8b15d9de21cc80ced442f29b4c5eb2b7802da89af895d6886` (`config.toml`)
- 3 trials in `trials.jsonl`
- search stopped: exhausted its plan (every grid point solved), converged

## Bounds

- `K`: 5e-05 to 0.0002 m/s, log

## Phases

| phase | status | restarts | frozen | best trial | stopped |
|---|---|---|---|---|---|
| k_grid | completed | 0 | none | 2 | exhausted its plan (every grid point solved) |

## Best trial

- trial 2, cost 0.002899
- calibrated run of `calage`: `runs/calage` (sim_id `83dee61c-53b9-4f5e-b68d-51e0b2181c75`)

## Where is what

- `session.json`: this session; `phases/<phase>/session.json`: each phase
- `trials.jsonl`: one trial per line, numbered once across phases
