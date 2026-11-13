# Calibration calage

Session `2473cfc06b9943a1b59b0c180ac9db26` of site `unnamed`, method `grid`, cost `rmse`, status **completed**.

- started 2026-11-13T20:46:42.552432+00:00, ended 2026-11-13T20:46:45.096029+00:00
- HydroModPy 2.0.0, configuration hash `9861331c156afb582064ac6a8f2eb53457a08b8a641feb03920c4c7f3b127cd4` (`config.toml`)
- 3 trials in `trials.jsonl`
- search stopped: exhausted its plan (every grid point solved), converged

## Bounds

- `K`: 5e-05 to 0.0002 m/s, log

## Phases

| phase | status | restarts | frozen | best trial | stopped |
|---|---|---|---|---|---|
| k_grid | completed | 0 | none | 2 | exhausted its plan (every grid point solved) |

## Best trial

- trial 2, cost 0.002899 (rmse)
- `K` = 0.0001 m/s, interval 0.0001 to 0.0001
- calibrated run of `calage`: `runs/calage` (sim_id `eab9575d-5f50-476e-953a-26a85ad30cfe`)

## Where is what

- `session.json`: this session; `phases/<phase>/session.json`: each phase
- `trials.jsonl`: one trial per line, numbered once across phases
