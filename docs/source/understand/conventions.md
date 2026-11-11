# Conventions of a run

A run stores numbers. This page says how to read them: which date reads which period, which
sign a flux has, what a station or a zone is called, and how layers and reaches are counted. The
rules are the same for every solver and they do not change from one model to the next.

## A date reads the period that holds it

A run has one value per stress period, and the time stored with a value is the end of its
period: the stamp. January 2000 of a monthly run is stamped 2000-02-01.

A date `t` reads the period `(s, e]` that holds it, where `s` is the start of the period and `e`
its stamp. So a date equal to a stamp reads the period that stamp closes, and a date copied from
the time axis of a NetCDF file or from a CSV finds its own value again. The first date of the
record belongs to the first period.

| Monthly run from 2000-01-01, `time =` | Period read | Stored stamp |
|---|---|---|
| `"2000-01-01"` | January 2000 | 2000-02-01 |
| `"2000-01-15"` | January 2000 | 2000-02-01 |
| `"2000-02-01"` | January 2000 | 2000-02-01 |
| `"2000-02-02"` | February 2000 | 2000-03-01 |

A state, such as a head, is the value at the stamp. A flux, such as a drain flux, is the mean over
the period. So a date inside a period reads the state at the end of that period. On a daily run,
`time = "2002-10-15"` reads the period that ends at the start of 15 October, which is the day of
14 October.

A window from `start` to `end` keeps every period with some time between the two dates. Two stamps
keep the periods between them, so `2001-01-01` to `2002-01-01` is the twelve months of 2001 on a
monthly run. A window of one date reads the period that date reads. A window that only touches the
record holds no period and is refused: it starts on the last stamp, or ends on the first date.

A window over a series keeps what falls in those periods. A simulated value is kept by its stamp,
`(start, end]`. A measurement is kept by its date, `[start, end)`. So `2000-02-01` to `2000-03-01`
is the one simulated value of February and the 29 daily measurements of February. A measurement
taken before or after the simulated record is read with the whole series, without a window.

A list of dates reads one period per date. A list where two dates read the same period is refused,
and the message names them: `2000-01-01` and `2000-02-01` both read January on a monthly run. To
read every period between two dates, write a window.

The rule is the same in `Run.read`, `run.field`, `run.timeseries`, `[[export]]`, `[display]` and the
`time` of a network output of a calibration. How a run stamps its periods is on
{doc}`/theory/time-alignment`.

## A budget flux is negative when water leaves the aquifer

Every per-cell flux of the `budget/` group of a run follows the sign of MODFLOW, for every solver:
positive when water enters the aquifer, negative when it leaves. A drain flux is negative. A
recharge is positive. A storage term is positive when the aquifer takes water from its storage. A
well is negative when it pumps. A transient run of every solver writes its storage terms. Summed
over the whole model domain, the signed fluxes add up to zero. This does not hold on one cell,
because the flows between cells are not in `budget/`.

The fields rebuilt from these fluxes say what they hold in their name: `outflow_drain`,
`release_flux` and the accumulation fluxes are positive outflows. The `budgets` table splits each
term in `flux_in` and `flux_out`, both positive. In a budget table, `flux_in` is the water that
enters the store named by `zone_id`: the aquifer for `DOMAIN`, the stream network for `sfr:<id>`,
the lake for its station. The exchange between two stores is therefore read with the sign of the
store its row names.

## A rate in a TOML file follows the same sign, or its name says the direction

A rate you write in a file has one of two forms, whatever the table.

A signed rate follows the rule of the budget: positive when water enters the store it acts
on, negative when it leaves. These are the rate of a well, {toml}`flow.sinks_sources.wells.<name>.flux`
and its forcing, the recharge, {toml}`flow.sinks_sources.recharge.values`, and the rate of a
specified lake outlet, {toml}`flow.sinks_sources.lakes.<name>.outlets.rate`, where the store is the lake.

A rate whose name says its direction is a magnitude, zero or more, and a negative value is
refused. These are the ETP values, and on a lake or a stream network `rainfall`, `evaporation`,
`runoff`, `inflow`, `withdrawal` and `headwater_inflow`. So a withdrawal of 2 m3/s takes 2 m3/s
out of the lake, and a well that takes as much says `-2`.

Water that leaves is written one of two ways. In the `budget/`
group, and in a rate that is signed (a well, a recharge, a specified lake outlet), it is
negative. In a rate whose name says the direction (`evaporation`, `withdrawal`, the ETP), it is a
positive magnitude.

## One word for the whole catchment

`catchment` means the whole catchment wherever a table needs a word for it: the station of a
catchment series such as `discharge`, the zone of a budget row, the zone of a uniform parameter, and
the soil column of the basin mean. `domain` is the zone of a budget row over the whole model domain.
The two differ when the mesh takes in a buffer around the catchment, so only the `catchment` row
compares with a gauge at the outlet.

A station or a zone you name cannot be called `catchment`, in a file or in a TOML key. A gauge with
this name would be scored against the simulated outlet, and a zone would read as a uniform
parameter. Write the gauge code, such as `J0014010`, or name the zone after what it holds, such as
`core` or `hillslope`. `domain` stays free: only a budget row reads it, and `catchment_zones` uses it
as a zone label.

## A column says where a series comes from

The `source` column of the `timeseries` table says `simulated` or `observed`. A simulated discharge
and a gauged one have the same variable, `discharge`. To read the gauge by name, `Run.read` and
`[[export]]` take `discharge_obs`, which no table stores. A CSV export has the same `source` column.

## How things are counted

| What | First value | Where |
|---|---|---|
| Layer | 0, the top layer | Everywhere |
| Period and time step | 0 | `timestep` of a table, `time` of a read |
| Cell | 0 | `cell_id` of a table, rank on the face axis of a field |
| Reach | 1 | `reach` of `sfr_reaches`, `upstream` and `downstream` of a TOML reach |

A reach keeps one number between the TOML and the results. Its `reach_id`, `<network>:<reach>`, is
its `station_id` in the `timeseries` table, and the table `sfr_reaches` gives its geometry and the
reaches it drains into.

A NetCDF variable or a VTU cell array keeps its name at any number of layers. A field with layers
has a `layer` dimension in a NetCDF file and one component per layer in a VTU file, on every solver:
`ds["drain"].isel(layer=0)` reads the top layer of a Boussinesq run as it does of a MODFLOW one.
QGIS reads a NetCDF file with one layer asked for: `hmp export` with `--layer`, or `layer =` in
`[[export]]`.

## Units

The `unit` column of a table, and the `units` attribute of a field, are written in udunits spelling:
`m3 s-1`, `mm d-1`, `m`, `1` for a dimensionless value. A text that is not plainly a unit stays as
its provider wrote it, such as `mg/L NO3` or `n/a`. The columns of the `soil_budget` table hold
water depths in the unit its `unit` column says, `mm`.
