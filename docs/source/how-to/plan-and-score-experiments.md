# Plan experiments and score them later

A plan of experiments runs one model at many points of a box of parameters. This page shows how to draw the points, then how to score the stored runs again on any window, without a new solve.

## Draw the points

A `[sites]` project can draw its own recipes. `[sites.design]` names a method, a number of points, a seed and the parameters that move. Each point becomes a case, named `<site>-p0001`, `<site>-p0002` and so on. For `lhs` the lot is part of the name, `b1p0001`. The drawn values go to `cases.csv` of the plan.

```toml
# not checked: a [sites] project has no [site], so it does not load on top of example 04
[sites]
table = "sites.csv"

[sites.recipes]
base = "project.toml"

[sites.design]
method = "sobol"
n = 64
seed = 1
recipe = "base"

[sites.design.parameters.K]
path = "flow.param.K.field.value"
bounds = [1e-7, 1e-3]
sampling = "log_uniform"

[sites.design.parameters.Sy]
path = "flow.param.Sy.field.value"
bounds = [1e-4, 0.35]
sampling = "log_uniform"
```

`sampling` is always written, because a uniform default on a parameter that spans three decades would put almost every point in the top decade. `method` is `sobol`, `lhs` or `grid`. `seed` is required for `sobol` and `lhs`, so that two expansions give the same points and the same case names. Doubling a Sobol `n` keeps the first points, and a second lot of `lhs` (`n = [60, 60]`) keeps the first one. A run that finished is not run again. `hmp check` and `hmp run --dry-run` read the design like any other plan.

## Score one run

A run stores its simulated and observed series. `run.score` pairs them as the seal did and gives one row per station, variable, metric and window.

```python
import hydromodpy as hmp

project = hmp.open("my_project")
run = project.runs()[0]

table = run.score(
    windows={"dry": ("2016-06-01", "2016-10-31"), "all": (None, None)},
    metrics=["nse", "kge"],
)
```

`windows` maps a name to a start and an end, either one may be `None`. Without `windows` the run is scored on the window of its own `[metrics]`, and the numbers are those of its seal. Without `metrics` every metric of a series pair is computed. `station` picks one station. The columns include `value`, `n_samples` and `n_sim_nan`, the number of periods lost to a missing simulated value.

`months` keeps the periods that fall in the given calendar months, after the pairing.

```python
summer = run.score(windows={"w": ("2010-01-01", "2018-12-31")}, months=[6, 7, 8, 9])
```

A mean period counts when all its days are in the months. A metric that needs consecutive days, such as `bfi_gap`, is refused on a masked window. `nse_seasonal` needs two full cycles in what is left.

## Score a set of runs

`runs.score` takes the same arguments and stacks the rows of every run, with the parameters of each run as columns. `runs.timeseries` stacks the stored series themselves.

```python
runs = project.runs()
table = runs.score(windows={"w": ("2016-01-01", "2018-12-31")}, metrics=["nse"])
series = runs.timeseries(station="J0014010", variable="discharge")
```

A run with no series at that station gives no row, with a warning.

## Score the stream network

`run.score_network` scores the stream network of a stored run as a calibration trial scores it, from the settings the run sealed or the defaults. The table has one row per quantity, bound and year. The numbers equal those of a trial when the run stored its fields with `[simulation.results.persistence] field_precision = "exact"`. With the default `compact` precision, a cell right at the seepage threshold can flip, so write `exact` in the plan when the network scores matter.

```python
network = runs.score_network(window=("2001-01-01", "2010-12-31"))
```

The network metrics `distance_gap` and `distance_mean` are given here and not by `score`, as quantities such as `J_signed` and `D_so`.

## Score a whole workspace

`hmp.index` opens a workspace. Its `score` and `score_network` run the set methods on every project and add a `project` column in front.

```python
workspace = hmp.index("~/hydromodpy")
table = workspace.score(windows={"w": ("2016-01-01", "2018-12-31")}, metrics=["nse"])
network = workspace.score_network()
```

## Score at collect

`hmp campaign collect` can do the same for every run of a `[sites]` project. Each `[[sites.summary.window]]` block names a window, and the collect writes `summary/scores.parquet` with the metrics of `[sites.summary]`.

```toml
# not checked: part of a [sites] project
[[sites.summary.window]]
name = "dry-summers"
start = "2010-01-01"
end = "2018-12-31"
months = [6, 7, 8, 9]
```

## Look at the plane of two parameters

The figure `parameter_space` draws each run as a point on log axes, coloured by one score. `variable` names the two parameters, and a third name picks the score. It is a metric of `score`, or a quantity of `score_network`. `time` gives the window. `station` picks one station, or the bound of a network quantity scored on two bounds.

```python
runs.figure("parameter_space", variable=["K", "Sy", "kge"], time=["2016-01-01", "2018-12-31"])
runs.figure("parameter_space", variable=["K", "Sy", "J_signed"])
```

A ring marks a run whose simulated series has missing values in the window, because its score covers fewer periods. The months mask is not a figure option. Score with `months` and read the table.

## Read a ridge in a calibration

A calibration that runs a `lhs` or a `grid` phase writes `ridge` in the report of the phase. It takes the best fifth of the trials, at least five, and reads them in search space, each axis scaled to the width of its bounds. It gives the Spearman correlation of each pair and `axis_ratio`, the square root of the ratio of the largest to the smallest eigenvalue of their covariance. A round cloud gives a ratio near one. A narrow cloud along a diagonal gives a large ratio and a correlation near one, which says the data fix a combination of the parameters and not each one.
