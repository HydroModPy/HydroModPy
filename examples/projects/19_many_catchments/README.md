# Example 19: many catchments

Two Breton catchments, the Nançon at Lécousse and the Canut at Maxent, each run two ways:
the model as it is, and a short calibration of K on its gauge. One project holds the four
cases. Monthly transient 2011-2015 with MODFLOW 6, on public data: Hub'Eau for the gauge,
SIM2 for the recharge and the runoff, BD Topage for the mapped network. Only the regional DEM
is a local file.

## The files

- `project.toml`: the model, written once for every catchment, and the `[sites]` section
  that turns it into a plan. It names no outlet and no station: those belong to one
  catchment and come from the site table.
- `sites.csv`: one row per catchment. `[sites.bind]` copies each column into the key it
  names: the site name, its label, its gauge, its outlet. `k_low` and `k_high` are read by
  the calibration recipe only.
- `calibration.toml`: the calibration recipe. It inherits `project.toml`, adds a
  `[calibration]` section and two bind lines of its own: the bounds of K and the station
  the hydrograph is scored on, both from the row of each site.
- `site_overrides/nancon.toml`: what differs for one site, an ordinary TOML applied on top
  of its row. Here the cross-section of the Nançon, oriented on its valley.

A case is a site crossed with a recipe: `nancon-base`, `nancon-calibration`, `canut-base`,
`canut-calibration`. The keys of a case come, lowest first, from the defaults,
`project.toml`, the row of `sites.csv`, `site_overrides/<site>.toml`, the keys the recipe
writes itself, then `--set`.

## Commands

From this folder, in a HydroModPy workspace that holds `data/dem/DEM_armorican_massif.tif`:

```bash
hmp config check project.toml          # the four cases, every error at its cell
hmp run project.toml --dry-run         # the plan, the solves, the scratch; nothing written
hmp run project.toml                   # the four cases
hmp run calibration.toml               # the calibration recipe alone, on both sites
hmp project collect .                  # summary/
```

The first run needs network access for Hub'Eau, SIM2 and BD Topage; the downloads are
cached after it.

## Where the outputs are

- `plan/<hash>/`: the resolved TOML of every case, replayable alone, and the site table as
  it was read.
- `runs/<case>/`: one run per case. A calibration case writes its trials under
  `sessions/<case>/` and promotes its best trial to `runs/<case>/`.
- `summary/`: written by `hmp project collect` from `[sites.summary]` and
  `[[sites.export]]`: one row per case (`by_case`), one per site with its best calibrated
  case (`by_site`, also as a GeoPackage map), the cohort figures of K and of the NSE, and
  the discharge of the best case of each site.
- `jobs/`: the journal of each launch.

Every case is scored on the window of `[metrics]`, 2012-2015; 2011 is spin-up.
