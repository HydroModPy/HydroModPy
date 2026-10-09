# Run in the background

```{hmp-task}
Task
: Start a run that outlives your terminal, follow it, stop it, and recover. Then call a step of HydroModPy from another program.

Time
: A minute to set up. The run takes its usual time.

Needs
: A run file that works in the foreground, and a Unix shell.

Gives
: A log file, a status you can read while it runs, and an exit code to test.
```

HydroModPy has no server and no job queue. A background run is an ordinary `hmp run` that your
shell or your scheduler starts and does not wait for. This page shows how to start one, how to
read its state, what happens when it is stopped, and how another program can call a step of
HydroModPy as an external process.

The examples use `step4_transient.toml` of example 04, which takes one to two minutes.

## 1. Start the run

```bash
cd projects/04_streamflow_intermittence_in_transient
setsid nohup hmp run step4_transient.toml > step4.log 2>&1 < /dev/null &
echo $! > step4.pid
```

`setsid` gives the run its own session and `nohup` ignores the hangup, so closing the terminal
does not stop it. The output goes to a file and the input is closed, so the run never waits for a
keyboard. On a cluster, put the same `hmp run` line in the job script of your scheduler.

To keep the exit code, write it in the log when the run ends:

```bash
setsid nohup bash -c 'hmp run step4_transient.toml; echo "exit $?"' > step4.log 2>&1 < /dev/null &
```

`-q` keeps warnings and errors only. The log of a normal run lists the steps one by one and ends
with:

```text
Run completed: nightly_05 [2b11ef73] 13s
next: hmp catalog show nightly_05 | hmp catalog diff nightly_05 <other> | hmp export nightly_05 --list
```

The exit codes are those of {doc}`../reference/cli/exit-codes`: 0 for success, 15 for a solver
error, 130 for an interruption.

## 2. Follow it

```bash
hmp catalog watch
```

```text
# running (1)
  [live]  nightly_02  [58e732ab]  heartbeat 22s ago
```

The command reads a small file that the run refreshes every 30 s, so it works while the solver
holds the catalog. Three things to know:

- In the first seconds the run is still delineating the catchment and building the mesh, and
  the command prints `no running simulations.`. The run is registered when the solver is prepared.
- While the solver runs, the name of the run is not readable and the row shows `(no name)`. The id
  in brackets is the first eight digits of its `sim_id`.
- `[STALE]` replaces `[live]` when the last heartbeat is older than 10 minutes. `--stale-minutes N`
  changes the limit, and `--format json` gives the same rows as data.

`hmp catalog ls` shows `status=running` and then `status=completed` or `status=failed`. The
reference `@running` selects the run in a command: `hmp catalog show @running`.

## 3. Stop it, and recover

Send `SIGTERM`, as a scheduler or `kill` does:

```bash
kill -TERM "$(cat step4.pid)"
```

```text
[WARNING] Received signal 15; unwinding so the run closes its session.
Aborted by user.
```

The run exits with code 130, and its status in the catalog is `failed`. Ctrl+C does the same.
The failed run stays in the catalog with its folder, so you can look at it. Start it again from
its last journalled step:

```bash
hmp run --resume nightly_07
```

```text
Run completed: nightly_07.v2 [88b442b2] 121s
```

The resumed run is a new run, `nightly_07.v2`. The failed `nightly_07` is not changed.

A process that is killed without warning (`kill -9`, a lost node, a power cut) cannot close its
run. The run stays `running`, and `hmp catalog watch` flags it `[STALE]` after 10 minutes. Then:

```bash
hmp catalog gc
```

```text
[plan] stale_running_sims: 1 candidate(s)
  - 04_streamflow_intermittence_in_transient:b3e5655b-6864-405f-9d41-6e7cd347930d
…
Plan only. Re-run with --apply to execute.
```

`hmp catalog gc --apply` marks the stale run `failed`. Read the plan first: the same command
also lists runs to trash by the retention rules of {doc}`clean-and-reindex-runs`.

## 4. Call a step from another program

`hmp process` is the interface for a program that runs HydroModPy as an external process. It does
not run a simulation. It serves three capabilities, each one a function from a request to a
directory of sealed files:

```bash
hmp process list
```

```text
data-request       1.0.0  Serve [data] sections over an extent and a period, one file per variable
domain-build       1.0.0  Aquifer domain geometry from a terrain and a depth model
terrain-delineate  1.1.0  Watershed delineation from a DEM and one or more outlets
```

`hmp process describe terrain-delineate` prints the full description as JSON: the inputs, the
outputs, the errors it can return, and how to call it.

### One job

The caller makes a job directory and writes `request.json` in it. The request names the
capability and its inputs. Here a DEM clipped around the outlet of example 04:

```python
import rasterio
from rasterio.windows import from_bounds

x, y, r = 389285.910, 6816518.749, 6000  # outlet and half-width, m
with rasterio.open("data/dem/DEM_armorican_massif.tif") as src:
    window = from_bounds(x - r, y - r, x + r, y + r, src.transform)
    profile = src.profile | {
        "height": int(window.height),
        "width": int(window.width),
        "transform": src.window_transform(window),
    }
    with rasterio.open("dem_nancon.tif", "w", **profile) as dst:
        dst.write(src.read(1, window=window), 1)
```

The script {download}`recipes/delineate_job.sh` writes the request, runs the job and checks it:

```bash
bash delineate_job.sh dem_nancon.tif 389285.910 6816518.749 EPSG:2154
```

```text
exit code 0, job directory /tmp/hmp-job.kHTM0N
/tmp/hmp-job.kHTM0N: sealed, and every artefact still hashes to what the seal recorded
```

The process keeps three promises:

- **Standard output is one JSON document**, byte for byte the same as `outcome.json`. Everything
  meant for a person goes to standard error, such as
  `[WARNING] Outlet moved 118 m (limit 150 m) onto the flow network, from (389286, 6816519) to (389174, 6816482).`
- **The exit code is the one in the outcome**: 0 for `successful`, and a typed code otherwise. The
  document has `status`, `exit_code`, the list of `outputs` with their SHA-256 digests, and
  `errors` with a `code` such as `HMPY.E101`.
- **`SIGTERM` unwinds.** The outcome says `dismissed`, nothing is sealed and the exit code is 130.

The directory then holds `outputs/` (here `watershed.gpkg`, `watershed.parquet`,
`outlets_snapped.geojson`, `flow_direction.tif`, `flow_accumulation.tif`, `dem_corrected.tif`),
`inputset.json`, `provenance.json`, `outcome.json` and, written last, `manifest.json`. The
manifest exists if and only if the job succeeded, so a caller never has to guess.
`progress.ndjson` and `logs/` are not part of the seal: read `progress.ndjson` to follow a long job.

The same request again does not run twice. The process answers with the stored outcome, with
`"reused": true`, writes nothing and exits 0. A job directory sealed for another request is
refused.

```bash
hmp process verify --job /tmp/hmp-job.kHTM0N
```

`verify` recomputes the digests of the files against the seal and prints the line above. When a
file changed, it lists the problems, for example
`outputs/outlets_snapped.geojson does not hash to what the seal recorded`, and exits 16.

### A chain of jobs

`hmp process chain --root DIR` runs several capabilities in a row, each one filling an input from
a file of an earlier one. The root holds `chain.json`. This one delineates a catchment, then builds
the domain on the same DEM with the catchment as its mask:

```json
{
  "steps": [
    {
      "id": "delineate",
      "process": {"id": "terrain-delineate"},
      "inputs": {
        "dem": {"href": "/path/to/dem_nancon.tif"},
        "outlets": [{"site_id": "nancon", "x": 389285.910, "y": 6816518.749}],
        "crs_project": "EPSG:2154",
        "snap_distance_m": 150
      }
    },
    {
      "id": "domain",
      "process": {"id": "domain-build"},
      "inputs": {
        "dem": {"href": "/path/to/dem_nancon.tif"},
        "depth_model": {"kind": "constant_thickness", "thickness": "30.0 m"}
      },
      "links": [{"member": "mask", "step": "delineate", "output": "watershed_vector"}]
    }
  ]
}
```

```bash
hmp process chain --root /scratch/chains/17 > out.json 2> err.log
```

Each step gets its own job directory, `01-delineate/` and `02-domain/`, and the chain writes
`chain-outcome.json` at the root, with the status and the exit code of every step. Links are
resolved before the first step runs, so a link to an output that does not exist is refused at
once. A step that fails stops the chain, and the later steps are reported as `skipped`.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `hmp catalog watch` reads `no running simulations.` right after the start | The run is still delineating and meshing | Wait for the solver step, or read the log |
| A run stays `running` after its process died | The process was killed without a signal it can handle | `hmp catalog gc --apply` after 10 minutes marks it `failed` |
| `Aborted by user.`, exit 130 | `SIGTERM` or Ctrl+C | The run is `failed` and `hmp run --resume <name>` continues it |
| The run stops when the terminal closes | It was started without `setsid nohup`, or inside a session the scheduler ends | Start it as in section 1, or use the scheduler |
| `no capability named 'x'; this build serves data-request, domain-build, terrain-delineate`, exit 2 | A wrong capability id | Run `hmp process list` |
| An outcome with `"status": "failed"`, `"code": "HMPY.E101"` and exit code 14 | The request does not validate. The detail names the member, such as `inputs.outlets: List should have at least 1 item after validation, not 0` | Fix `request.json` and run again in a new job directory |
| `"reused": true` and no new files | The same request was already sealed in this directory | Use a new directory to run again |

## Next

- Find and compare the runs that finished: {doc}`find-and-compare-runs`; clean them:
  {doc}`clean-and-reindex-runs`.
- Drive runs from a script: {doc}`drive-from-python`.
- The options of the commands: {doc}`../reference/cli/run`, {doc}`../reference/cli/process` and
  {doc}`../reference/cli/catalog`.
