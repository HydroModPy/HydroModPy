# Doc health dashboard

Internal checklist tracking the documentation build health. Not
published. Updated on every Phase 2/3 doc commit and as part of any
ad-hoc audit.

Treat each row as a contract: when a number changes, either the change
is intentional (and this dashboard moves with it) or it is a
regression to fix before commit.

## Build health (local, `python -m sphinx -j auto -b html`)

| Metric | Target | Last known value | Notes |
|---|---|---|---|
| Build status | succeeds | succeeds | Run from repo root, `mamba activate hmp_refact` |
| Wall time | < 6 min | ~3 min | Parallelism via `-j auto` is mandatory |
| Pages emitted | grows monotonically | ~900 | Most pages are autosummary-generated |
| Warnings (incremental rebuild) | 3 (baseline) | 3 | Cached output suppresses docstring-parse warnings |
| Warnings (fresh build, ``rm -rf docs/build``) | <= 8 (current ceiling) | 8 | The extra 5 are pre-existing codebase docstring issues |
| Substantive warnings introduced by Phase 2 | 0 | 0 | New non-baseline warnings are a regression |

### Baseline warnings on every build (3, acceptable)

Tracked since Phase 1 step 18 and remain acceptable until the
underlying modules are restored:

1. `[autosummary] failed to import hydromodpy.data.variables.hydrometry.discovery`
   — depends on `hydromodpy.data.variables.common` which is missing.
2. `[autosummary] failed to import hydromodpy.data.variables.piezometry.discovery`
   — same root cause as 1.
3. `[autosummary] failed to import hydromodpy.workflow.pipelines.overview`
   — depends on `hydromodpy.workflow.pipelines.overview_config` which is missing.

### Extra warnings on fresh builds only (5, pre-existing)

These appear when ``docs/build`` is wiped and Sphinx parses every
module docstring from scratch. They are codebase-level docstring or
typing annotations issues, not regressions of the v1 documentation
refactor:

- Anonymous `Unexpected indentation` / `Block quote ends without a
  blank line` lines (no file path reported) emitted by docutils
  during autodoc parsing of Python docstrings.
- `Cannot resolve forward reference in type annotations of
  hydromodpy.spatial.field.core.field_spatial_weighted_discretization
  .WeightedAverageFieldDiscretization: name 'BaseFieldMesh' is not
  defined` from `sphinx-autodoc-typehints` ; needs the codebase to
  rebuild forward refs.
- `Could not match a code example to HTML, source: ...` from
  `sphinx-codeautolink` on a `>>>` example block.

A non-baseline warning introduced by Phase 2 is a regression and
must be fixed before commit. The five extra warnings above predate
Phase 2 ; the dashboard tracks them so they don't get lost.

## Doc linting

| Tool | Scope | Status |
|---|---|---|
| `sphinx-lint` | RST sources | clean on hand-written pages |
| `doc8` (max 100 cols) | RST sources, excludes `config_reference/*` | clean |
| `make html-strict` | warnings-as-errors gate | opt-in, expected to fail until baseline 3 are fixed |

## Coverage

| Surface | Source of truth | Coverage |
|---|---|---|
| Top-level config sections | `HydroModPyConfig.model_fields` | 17/17 sections have a Couche 2 page (workflow Literal omitted) |
| Validation gallery cases | `_static/capability_gallery/validation/*_summary.json` | 25 cases with summary JSON |
| Solver backends | MODFLOW-NWT, MODFLOW 6, Boussinesq, GR4J | row in compact matrix + dedicated page |
| Catchments deployed | `applications.rst` registry | 5 sites listed, more pending |

## Stub pages and outstanding work

- `examples/index.rst` is a "coming soon" placeholder. No regression
  if the slot stays empty until tutorials migrate.
- `_legacy_notebooks/*` are quarantined and not part of the public
  toctree. Do not promote them back without converting to TOML-first.
- The "Sphinx polyversion" migration (Phase 1 step 21) is deferred and
  should be picked up before tagging v1.0.

## Cross-link checks

- Config section pages link to gallery cases via
  `tools/doc_config._scan_section_to_cases`. Forward direction only.
  Inverse direction (gallery -> config) is deferred because it would
  invade `tools/doc_gallery` PNG drift baselines.
- Migration guide uses the API stability roles defined in
  `docs/source/_ext/hmp_directives.py`.

## Refresh procedure

1. Run `python -m tools.doc_config` to refresh
   `docs/source/user_guide/config_reference/` whenever a Pydantic
   field changes in `HydroModPyConfig`.
2. Run `python -m sphinx -j auto -b html docs/source docs/build/html`
   from repo root, with `mamba activate hmp_refact`.
3. If a warning count diverges from the table above, update the row
   in the same commit that introduced the change.
4. For a regression, fix the root cause; do not adjust the table to
   hide it.

## Future hooks

- `make html-strict` should become CI-blocking once the three baseline
  warnings are resolved upstream in the codebase.
- A nightly schedule could scrape `docs/build/html/` for broken links
  via `linkchecker` and post a delta to this file.
