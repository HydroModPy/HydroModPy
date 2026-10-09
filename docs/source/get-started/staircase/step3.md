# Step 3: the same data, from the APIs

```{hmp-task}
Task
: Fetch the river network and the gauge from the BD Topage and Hub'Eau APIs instead of local files.

Time
: About 40 s for the run once the data are cached. The first launch adds the downloads.

Needs
: **Network access** on the first run, no key. The example files ({doc}`index`).

Gives
: Five figures and six files, with the permanent reaches of the network as a GeoPackage of their own.
```

Step 3 is step 2 with other sources. The network comes from BD Topage and the gauge from
Hub'Eau, two French national APIs, instead of files on disk. Nothing else changes in the
model. The answers are cached after the first launch, so a second run needs no network.

```{image} /_static/figures/staircase/step3/hydrographic_network_permanence.webp
:alt: Two maps of the BD Topage network over the catchment. On the left every mapped reach, on the right only the reaches that flow all year.
:class: only-light
:width: 80%
:align: center
```

```{image} /_static/figures/staircase/step3/hydrographic_network_permanence-dark.webp
:alt: Two maps of the BD Topage network over the catchment. On the left every mapped reach, on the right only the reaches that flow all year.
:class: only-dark
:width: 80%
:align: center
```

## The file

::::{tab-set}

:::{tab-item} The file
```{hmp-step} step3_api_data.toml
```
:::

:::{tab-item} Changed vs step 2
The resolved file of step 3 against the resolved file of step 2.

```{hmp-toml-diff} step2_local_data.toml step3_api_data.toml
```
:::

::::

## Run it

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run step3_api_data.toml
```
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("step3_api_data.toml")
```
:::

::::

The first launch downloads from BD Topage and Hub'Eau. The later ones read the cache.

`sources__delete = true` empties the inherited list of sources before the new one is
written, so no local key leaks into it. An API also needs a period, which the file gives:
the three years that step 4 simulates.

## What you get

| Figure | What it shows |
|---|---|
| `watershed_id_card` | As in step 1 |
| `hydrographic_network_reference` | Every BD Topage reach |
| `hydrographic_network_permanence` | Two maps of the network: all the mapped reaches, and only those that flow all year |
| `seepage_network_confusion_map` | As in step 2, against every reach of BD Topage |
| `downslope_distance_map` | As in step 2 |

The exports are step 2's four, plus the permanent reaches as a GeoPackage of their own:
six files in `share/nancon_step3_api/`.

## Key fields

```{hmp-params}
data.hydrography.sources.source
data.hydrometry.sources.source
data.hydrometry.sources.product
data.hydrometry.date_start
```

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `step 'load_data' failed: NetworkError: Failed to load data manager 'hydrography': HTTP GET https://services.sandre.eaufrance.fr/geo/sandre failed after 4 retries`, exit code 16 (after four `WARNING` lines with the same URL) | The first launch has to reach BD Topage and the machine has no route to it, or the service is down. The run stops: a source the file declares is never skipped. | Run again when the network is back. Behind a proxy, set `HTTPS_PROXY`. To run offline, run step 2, which reads local files, or run step 3 once online: the cache then holds its data, and {doc}`hmp run --frozen <../../reference/cli/run>` refuses any new download. |

The exit codes are listed on {doc}`../../reference/cli/exit-codes`.

Next: {doc}`step4`. It repeats the local data of {doc}`step2`.
