# Site Selection To Testbed

This example shows the hand-off from a site-selection result into the two
testbed entry points:

- generic `[testbed.catalog]`;
- regional-lab `[regional_lab.catalog]`.

Both examples read `fixtures/site_selection_manifest.json` and let HydroModPy
resolve `fixtures/regional_lab_sites.csv` through the manifest output map. In a
real campaign, replace the fixture manifest path with the
`site_selection_manifest.json` produced by a run under
`examples/projects/17_site_selection_workflow/outputs/...`.

## Generic testbed

`site_selection_catalog_testbed.toml` expands every selected site into one mesh
simulation child config. It defaults to `execute = false`, so it only writes the
testbed plan and generated child TOMLs.

```bash
hmp run examples/projects/18_site_selection_to_testbed/site_selection_catalog_testbed.toml
```

The catalog section is the important part:

```toml
[testbed.catalog]
from_site_selection_manifest = "fixtures/site_selection_manifest.json"
output = "regional_lab_sites_csv"
id_field = "site_id"
label_field = "site_label"
axis_field = "region_id"
tags_field = "tags"
field_equals = { site_status = "selected" }
```

## Regional lab profile

`site_selection_regional_lab.toml` uses the same manifest as a regional site
inventory. It plans one simulation recipe and one comparison recipe per selected
site. `validate_config_paths = false` keeps this as a planning example; provide
real child TOMLs and switch validation/execution on for a production campaign.

```bash
hmp run examples/projects/18_site_selection_to_testbed/site_selection_regional_lab.toml
```

The regional catalog section mirrors the generic hand-off:

```toml
[regional_lab.catalog]
from_site_selection_manifest = "fixtures/site_selection_manifest.json"
output = "regional_lab_sites_csv"
site_id_field = "site_id"
site_label_field = "site_label"
region_field = "region_id"
tags_field = "tags"
```

The top-level regional selection uses the status exported by site selection:

```toml
[regional_lab.selection]
statuses = ["selected"]
```

## Real site-selection output

Run a site-selection workflow first:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/aura_non_jauge_csv_50_150km2.toml
```

Then point either catalog section to the generated manifest:

```toml
from_site_selection_manifest = "../17_site_selection_workflow/outputs/aura_non_jauge_csv_50_150km2_v1/site_selection_manifest.json"
```

The downstream config no longer needs to hard-code
`regional_lab_sites.csv`; the manifest remains the stable hand-off contract.

For an execution campaign, keep the manifest-based catalog and provide real
child TOMLs for every rendered recipe path. Then switch:

```toml
[regional_lab]
execute = true
validate_config_paths = true
```

## Regenerated regional testbeds

The files below show the intended migration path for the larger natural
campaigns: regenerate a site inventory with `site_selection`, then let the
comparison testbed consume the resulting manifest.

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_non_jauge_dem_8bassins_10km2.toml
hmp run examples/projects/18_site_selection_to_testbed/bretagne_10km2_mf6_bouss_from_site_selection.toml
```

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_non_jauge_dem_9bassins_100km2.toml
hmp run examples/projects/18_site_selection_to_testbed/bretagne_100km2_mf6_bouss_from_site_selection.toml
```

The first pair targets the legacy N1 scale: about 8 sites near 10 km2. The
second pair targets the legacy N2 scale: about 9 sites near 100 km2. The sites
are regenerated from DEM area targets and are not expected to match the old
static `natural_regional_lab_sites.csv` rows.
