# Regional Lab Summary: headwater_100km2_lab

- Config: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\regional_lab\config_headwater_100km2_lab.toml`
- Site catalog: `C:\codes\HydroModPy-GH\examples\projects\launcher_simulation\regional_lab\site_catalog.csv`
- Selected sites: 5
- Planned cases: 3
- Skipped cases: 6
- Executed cases: 0
- Reused cases: 0
- Failed cases: 0

## Recipes

| Recipe | Candidate sites | Planned | Skipped | Executed | Reused | Failed | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| mf6_reference | 3 | 1 | 2 | 0 | 0 | 0 | 1 |
| backend_compare | 3 | 1 | 2 | 0 | 0 | 0 | 1 |
| transient_backend_compare | 3 | 1 | 2 | 0 | 0 | 0 | 1 |

## Clusters

| Cluster | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| headwater_100km2 | 3 | 3 | 6 | 0 | 0 | 0 | 3 |
| s3_100km2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| s3_10km2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |

## Regions

| Region | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| brittany | 5 | 3 | 6 | 0 | 0 | 0 | 3 |

## Coverage Gaps

- `mf6_reference` / `headwater_100km2_outlet_27`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `mf6_reference` / `headwater_100km2_outlet_34`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `backend_compare` / `headwater_100km2_outlet_27`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `backend_compare` / `headwater_100km2_outlet_34`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `transient_backend_compare` / `headwater_100km2_outlet_27`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `transient_backend_compare` / `headwater_100km2_outlet_34`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
