# core/site

This folder answers: what is a site? A site is one catchment, declared once and recognized in every
project that models it, even in two workspaces.

## Modules, in the order a caller uses them

1. `config.py` is `SiteConfig`, the `[site]` section: a name, a label, the gauge that scores it, an optional URI and an outlet. It also has `site_fingerprint`, which recognizes a site from its declaration and never from a DEM, and `resolve_gauge`, the one source of the station that other keys fall back to (`GaugeConflictError` when they disagree).
2. `row.py` is `SiteRow`, one row of `data/sites/catalog.csv` (`SITE_ROW_COLUMNS`), the same columns that `hmp campaign collect --write-sites` writes.

## What other layers import from it

`config`, `project`, `data`, `workflow`, `results`, `cli` and `calibration`.

## Where to add what

- A new column of the site table: `row.py` and `SITE_ROW_COLUMNS`.
- A new site key: `config.py`, and check that `site_fingerprint` still ignores what must not change identity.

The layer rules are checked by `tests/unit/architecture/`.
