# Realistic Campaign

This folder turns the earlier discussion into one runnable campaign layer:

- `campaign.toml` is the inventory of realistic and flagship cases.
- `run_campaign.py` is a small sequential runner with filtering and JSON reporting.
- cases stay in their native launcher families (`simulation` or `method-comparison`);
  the campaign only orchestrates them.

The intent is to keep four roles separate:

- `validation_cases/` proves the physics on analytical cases.
- `tests/regression/` keeps CI-sized non-regressions stable.
- `realistic_campaign/` explores wider real or quasi-real studies.
- `examples/capability_gallery/` remains the curated, versionable showcase.

## Commands

List the inventory:

```powershell
python -m examples.projects.launcher_simulation.realistic_campaign.run_campaign --list
```

Dry-run the flagship subset:

```powershell
python -m examples.projects.launcher_simulation.realistic_campaign.run_campaign --tier flagship --dry-run
```

Run only the new 100 km2 MF6 scenarios:

```powershell
python -m examples.projects.launcher_simulation.realistic_campaign.run_campaign --region headwater_100km2 --launcher simulation
```

Run one exact case:

```powershell
python -m examples.projects.launcher_simulation.realistic_campaign.run_campaign --case headwater_100km2_mf6_transient_heterogeneous_decay
```

## Capability Gallery

The campaign is broader than the capability gallery.

- Simulation cases may publish a selected subset of figures through `[capability_gallery]`.
- Method-comparison cases keep their own outputs under `method_comparison/...`.
- The gallery should receive only a small curated subset after review.

## Technical Note

The new flagship heterogeneous + exponential-depth-decay case is implemented on `modflow6`.
The current Boussinesq 2D property-mapping path does not apply vertical decay in a meaningful
way, so using MF6 here keeps the example honest.
