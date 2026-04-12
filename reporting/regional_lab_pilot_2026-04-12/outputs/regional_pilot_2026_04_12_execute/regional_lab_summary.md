# Regional Lab Summary: regional_pilot_2026_04_12_execute

- Config: `C:\codes\HydroModPy-GH\reporting\regional_lab_pilot_2026-04-12\config_regional_lab_pilot_execute.toml`
- Site catalog: `C:\codes\HydroModPy-GH\reporting\regional_lab_pilot_2026-04-12\site_catalog_pilot_20.csv`
- Selected sites: 20
- Planned cases: 14
- Skipped cases: 27
- Executed cases: 3
- Reused cases: 0
- Failed cases: 2

## Recipes

| Recipe | Candidate sites | Planned | Skipped | Executed | Reused | Failed | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| headwater_mf6_reference | 10 | 1 | 9 | 1 | 0 | 0 | 0 |
| headwater_backend_compare | 10 | 1 | 9 | 1 | 0 | 1 | 0 |
| headwater_transient_backend_compare | 10 | 1 | 9 | 1 | 0 | 1 | 0 |
| headwater_local_boussinesq_replay | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| s3_future_reference | 10 | 10 | 0 | 0 | 0 | 0 | 10 |

## Clusters

| Cluster | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| headwater_100km2 | 10 | 4 | 27 | 3 | 0 | 2 | 1 |
| s3_10km2 | 10 | 10 | 0 | 0 | 0 | 0 | 10 |

## Regions

| Region | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| brittany | 20 | 14 | 27 | 3 | 0 | 2 | 11 |

## Coverage Gaps

- `headwater_mf6_reference` / `headwater_100km2_outlet_10`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_27`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_3`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_4`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_5`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_6`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_7`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_8`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_mf6_reference` / `headwater_100km2_outlet_9`: missing_required_fields (Missing required field(s): simulation_reference_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_10`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_27`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_3`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_4`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_5`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_6`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_7`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_8`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_backend_compare` / `headwater_100km2_outlet_9`: missing_required_fields (Missing required field(s): backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_10`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_27`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_3`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_4`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_5`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_6`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_7`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_8`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
- `headwater_transient_backend_compare` / `headwater_100km2_outlet_9`: missing_required_fields (Missing required field(s): transient_backend_comparison_config)
