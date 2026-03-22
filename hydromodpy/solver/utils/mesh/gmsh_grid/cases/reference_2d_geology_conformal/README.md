# Reference 2D Geology Conformal Case

This case demonstrates the 2D zone-conformal meshing workflow and produces
three QA outputs:

- `.msh` mesh file
- `.json` summary sidecar
- `.png` overview figure

The summary sidecar exposes a stable schema marker and QA diagnostics:

- `summary_schema_version = "zone_conformal_sidecar_v1"`
- `cleaning_summary` (compact tolerant-cleaning diagnostics)
- `physical_groups_summary` (surface/curve/interface/boundary counts)
- `qa_checks` (coverage gap/tolerance and quick conformity booleans)
- `constraints_mode` (`geology_only`, `rivers_only`, `geology_rivers`)

Architecture diagrams for the launcher/runtime/domain/river/zone pipeline are
documented in
`docs/readthedocs/source/architecture/mesh/catchment-conformal-meshing-diagrams.rst`.

## Constraints modes

The runner requires one explicit mode:

- `constraints_mode = "geology_only"`: geology constraints only
- `constraints_mode = "rivers_only"`: river constraints only
- `constraints_mode = "geology_rivers"`: geology + river constraints

## Domain contract

Supported domain modes are restricted to:

- `bbox`
- `polygon`
- `vector` (`path`, `id_field`, `selected_id`)
- `geographic_box_buffer`
- `geographic_watershed`
- `geographic_watershed_box`

No advanced mask/boolean domain contract is supported in this case.

When reading the code, the relevant public domain helpers are now:

- `parse_zone_meshing_domain_config(...)`
- `load_zone_meshing_domain_payload(...)` once one typed
  `ZoneMeshingDomainConfig` has been built

For an inline rectangular support, the expected contract is:

```toml
[mesh_case.domain]
kind = "bbox"
bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]
```
