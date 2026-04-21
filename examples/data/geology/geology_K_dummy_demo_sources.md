# geology_K_dummy_demo.csv - K value provenance

## File status

This file is a **demonstration dataset**.
It must not be used as hydrogeologic truth for site-scale studies.

- Dataset name: `geology_K_dummy_demo.csv`
- Property column: `K_value` (hydraulic conductivity, in m/s)
- Enforced value range: `1e-6` to `1e-3` m/s
- Coverage target: one row per `CODE_LEG` present in the bundled `GEO1M.shp`,
  plus `SEA`

## Source data

- Geology classes: `CODE_LEG` field from the France shapefile `GEO1M.shp`
- Geology labels: `geology_name` column
- Mapping key: `zone_key`

## How `K_value` was built

`K_value` was assigned using a **keyword-based heuristic** on `geology_name`,
using generic hydraulic-conductivity orders of magnitude.

Combination rules:

- If several lithologies appear in one label, the final value is the **geometric mean** of detected keyword values.
- If no keyword is recognized, fallback value is `1e-5` m/s.
- Final value is clamped to `[1e-6, 1e-3]` m/s.
- `SEA` case is fixed to `1e-6` m/s.

Reference material groups used:

- Coarse materials (pebbles, gravels, coarse alluvium): higher K
- Sands: medium to high K
- Sandstones / limestones: medium K
- Clays / marls / schists: low K
- Volcanic and pyroclastic rocks: medium K (demo assumption)

## Documentation sources (order-of-magnitude guidance)

These references are used only to define **generic** ranges:

1. USGS Professional Paper 2254 (conductivity range tables):
   https://pubs.usgs.gov/pp/2254/pp2254.pdf
2. USGS Water Budgets and Flow (hydraulic conductivity concepts):
   https://www.usgs.gov/mission-areas/water-resources/science/water-budgets-and-flow
3. USDA/NRCS National Engineering Handbook (K ranges by material):
   https://directives.sc.egov.usda.gov/OpenNonWebContent.aspx?content=17757.wba

## Recommendation

For scientific use, replace `K_value` with:

- local calibration values, or
- an expert table documented for each regional geologic unit.
