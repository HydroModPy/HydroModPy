# The staircase

Example 04 models the Nançon catchment (Ille-et-Vilaine) with MODFLOW 6. It ships as a
staircase of six TOML files. Each file inherits another one and writes only what it
changes, so the page of a step shows you only what that step adds.

| Step | File | What it adds | Inherits |
|---|---|---|---|
| {doc}`1 <step1>` | `step1_minimal.toml` | The shortest file that runs: steady state, local DEM, one K, one recharge rate | nothing |
| {doc}`2 <step2>` | `step2_local_data.toml` | The mapped river network and the gauge, from local files, compared with the simulated seepage | step 1 |
| {doc}`3 <step3>` | `step3_api_data.toml` | The same data, fetched from the BD Topage and Hub'Eau APIs | step 2 |
| {doc}`4 <step4>` | `step4_transient.toml` | Monthly transient run, 2000-2002, forced by observed recharge and runoff | step 2 |
| {doc}`5 <step5>` | `step5_export.toml` | The results written out in every format | step 4 |
| {doc}`6 <step6>` | `step6_soil_reservoir.toml` | Daily run, 2015-2020, recharge computed by a soil reservoir | `project.toml` |

Step 3 is a variant of step 2, not a rung above it. Step 6 starts again from
`project.toml`, the frozen reference model of the example.

```text
step 1 ── step 2 ─┬─ step 3   same data, from APIs
                  └─ step 4 ── step 5
project.toml ── step 6
```

## Get the example once

```bash
hmp workspace init ~/hydromodpy
hmp example add 04 -w ~/hydromodpy
cd ~/hydromodpy/projects/04_streamflow_intermittence_in_transient
```

`hmp example add` downloads 27 files, 92 MiB, most of it a regional DEM of 90 MiB. Files
are cached by content, so a second workspace costs nothing. `hmp example list` shows the
examples your version ships and `hmp example show 04` lists the files one by one.

Then run any step from that folder:

```bash
hmp run step1_minimal.toml
```

Each run writes its figures to `runs/<name>/figures/` and its exports to
`share/<name>/`, where `<name>` is the `[simulation] name` of the file.

```{note}
Run the same file twice and the second command stops and names the first run, because
the resolved config has not changed. Add `--force` to compute it again.
```

```{toctree}
:hidden:

Step 1: minimal <step1>
Step 2: local data <step2>
Step 3: API data <step3>
Step 4: transient <step4>
Step 5: export <step5>
Step 6: soil reservoir <step6>
```
