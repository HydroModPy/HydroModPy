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

No advanced mask/boolean domain contract is supported in this case.

## Migration note (`clip_bbox` removed)

`domain.clip_bbox` is no longer supported in this case workflow.

Required contract:

- `domain.kind = "bbox"`
- `domain.bbox = [xmin, ymin, xmax, ymax]`

Example migration:

```toml
[mesh_case.domain]
kind = "bbox"
bbox = [355000.0, 6712500.0, 359000.0, 6716500.0]
```
