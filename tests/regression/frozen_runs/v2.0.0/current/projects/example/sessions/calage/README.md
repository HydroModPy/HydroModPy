# Calibration calage

Session `15ed6e9bfc5e44558cf3537f3faa6f33` of site `unnamed`, method `grid`, cost `rmse`, status **completed**.

- started 2026-11-03T10:07:37.408668+00:00, ended 2026-11-03T10:07:40.083271+00:00
- HydroModPy 2.0.0rc1, configuration hash `e4e3158b175c919fc29fa7c5d857943fd219a81f13f85ed7c8d56614e3897e21` (`config.toml`)
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
- calibrated run of `calage`: `runs/calage` (sim_id `5e9559c0-d954-4ba2-84a4-3bcc0a2629a2`)

## Where is what

- `session.json`: this session; `phases/<phase>/session.json`: each phase
- `trials.jsonl`: one trial per line, numbered once across phases
