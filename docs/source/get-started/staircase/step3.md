# Step 3: the same data, from the APIs

Step 3 is step 2 with other sources. The network comes from BD Topage and the gauge from
Hub'Eau, two French national APIs, instead of files on disk. Nothing else changes in the
model. It needs network access the first time and no key. The answers are cached after
that.

## The file

```{hmp-step} step3_api_data.toml
```

## Run it

```bash
hmp run step3_api_data.toml
```

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

The exports are step 2's four, plus the permanent reaches as a GeoPackage of their own.
They land in `share/nancon_step3_api/`.

## Key fields

```{hmp-params}
data.hydrography.sources.source
data.hydrometry.sources.source
data.hydrometry.sources.product
data.hydrometry.date_start
```

Next: {doc}`step4`. It repeats the local data of {doc}`step2`.
