# Long transient runs in windows

A transient run over many years in daily periods can take hours. When I cut it into
windows, each window is a run of its own, sealed when it ends. A stop, a crash or a
power cut costs me the window in progress and nothing before it. This page says how I cut
a run, how I play it, how I stop it and how I start it again.

## Cut the run

I add a length to `[simulation.time]`. The length is a calendar length written with its unit.

```toml
[simulation.time]
start_datetime = "2010-01-01"
end_datetime = "2019-12-31"
step_value = "1 day"
window_length = "1 year"
```

The windows start at `start_datetime` and follow one another. The last one ends with the
simulation and may be shorter. If I want hydrological years, I start the simulation on the
first of October.

Every edge between two windows must fall on the end of a stress period. With daily periods
any length in days, months or years does. With periods of seven days, `"1 month"` is refused,
and the message names the edge and the two period ends around it. I change the length or the
step.

A run in windows needs a transient flow and a backend that can start from a saved state, which
is MODFLOW 6 today. It cannot carry a transport process and it is not a calibration trial. A
steady first period that takes the mean recharge or ETP (`first_clim = "mean"`, the default)
would average window 1 only, so it is refused too. I set `first_clim` to `"first"` or a number,
or I turn `flow.first_period_steady` off and start from `[flow.ic] kind = "steady_state"`, which
the chain computes over the whole simulation. The file is refused with the reason when it is
read.

## Play the windows

`hmp run project.toml` plays the windows one after the other. Each one is a sealed run named
after the run with `_w1`, `_w2` and so on. From ten windows the numbers have two digits, so the
names sort in order (`island_w01`, `island_w02`). Window 1 starts as the run in one piece would
start, from its starting heads. Window `k` starts from the `final_state/` of window `k - 1`,
and the run records that folder and its digest as an input.

I can play one window with `window = 2` in `[simulation.time]`. It needs window 1 sealed
first. Without it the run is refused and says to play window 1 first, or to set `window = "all"`.

The heads are meant to equal the run in one piece to the last bit. The page on
{ref}`the groundwater flow problem <gwf-windows>` gives the measure, and the one case where the
difference is not zero, SFR with storage.

## Start again after a stop

`hmp run project.toml` again gives back the windows that are sealed with the same request, and
says so for each one. It resumes the window that stopped and plays the ones after it. A window
resumes at the step it stopped in. A stop in the solve plays the solve again from its first
time step.

To stop a run on purpose I use `hmp stop`, from any terminal.

```bash
hmp stop island_w3
```

The command writes a flag in the run folder and returns at once. The run reads it between two
steps, and MODFLOW 6 through libmf6 also between two time steps. The run ends `aborted`, and the
chain stops with it. `hmp stop` works on a calibration session the same way.

`hmp run project.toml --resume island_w3` asks for the resume of that window and refuses when
something changed since the stop, an input or a key of the file. The refusal says so. A plain
`hmp run project.toml` starts the window over in that case. Without the file,
`hmp run --resume island_w3` reads the configuration the window froze in its folder, resumes it
and plays the windows after it.

The `config.toml` of a sealed window is the request of that window alone. `hmp run
runs/island_w2/config.toml --frozen` replays window 2 from the final state of the run its
`inputs.json` names, so window 1 must still be in the project.

## Read the time of each window

Each run writes `profile.json`, the time and the memory of each step, solve, figure and export.
`hmp catalog show island_w2` prints the total, the start-up, the solve of each run of the plan,
the three longest steps and what was reused. A run from version 2.0 has no profile, and the
command says so and prints the solve time its seal holds.
