# `hydromodpy/calibration`

Fitting model parameters to observations. A `[calibration]` table names the
parameters to vary, the outputs to compare, the criterion that scores them and
the search method. The package turns that table into a search: an optimizer
proposes parameter values, one trial runs the model with them, the outputs are
scored against the observations, and the session is written to disk as it goes.
This file is the map of the package: what each part answers, the import rules,
how a calibration flows, and where to add what.

## Parts

In dependency order, lowest first. A part is a subpackage or a module at the
root of the package.

| part | answers |
|---|---|
| `targets.py` | which parameters a resolved project exposes to calibration (`hmp config targets`) |
| `parameter_resolution.py` | what a `[calibration.parameters.<name>]` name means as a config path, at load |
| `criteria/` | how one simulated series is scored against one observed series: the scoring kernels (`METRICS` in `series.py`), their conventions, and the network distance |
| `optim/` | how the search runs: parameter space, objective, optimizer protocol and registry, engine, stopping, params-hash cache, uncertainty (FOSM, cost margin) |
| `optim/adapters/` | the search methods themselves: grid, random, scipy, CMA-ES, Optuna, bisection, GP mapping, DA-MH-GP |
| `persistence.py` | how a session is written: `sessions/<case>/` and its journal, nothing else |
| `report.py` | how a finished session is read back for the report, from its directory |
| `evaluation/` | what one trial must answer: the evaluator port and the forward-model port, their registries, and the two evaluators that need nothing from the calibration document |
| `config.py` | what the modeller wrote: every `[calibration.*]` table, protocol options included |
| `protocols/` | which published recipe a calibration follows, and how it expands into phases and objective blocks |
| `observations/` | what is observed: the observed stream network and its geometry |
| `metrics/` | how the outputs of one trial are extracted and paired with observations, and the evaluator that scores a forward model |
| `runners/` | how a calibration runs: the three entry points, the phases and what they hand to each other, the trial primitive, the default evaluator, restarts, resume, promotion of the best trials |
| `preflight.py` | every check of a calibration before anything is prepared, run at the start of every launch and printed by `hmp config check` |

The two analytical demonstrators that the regression tests drive from Python live outside the
package, in `validation_cases/calibration/unconfined_interface_1d/` and
`validation_cases/calibration/recession_hillslope_aquifer/`.

## Import rules

A part imports only what its row of
`tests/unit/architecture/calibration_layout.yaml` allows, and the layout test
checks every import: at module level, inside a function, under
`TYPE_CHECKING`. A row names only rows above it, so the table cannot allow a
cycle. Every part may import the layers `layer_matrix.yaml` gives calibration.

| part | may import |
|---|---|
| `targets`, `lumped`, `criteria` | nothing in calibration |
| `parameter_resolution` | `targets` |
| `optim` | `criteria` |
| `persistence` | `optim` |
| `report` | `persistence` |
| `evaluation` | `optim` (types only) |
| `config` | `criteria`, `evaluation`, `optim`, inside validators only |
| `protocols`, `observations` | `config` |
| `metrics` | `config`, `criteria`, `evaluation`, `observations`, `optim` |
| `runners` | `config`, `criteria`, `evaluation`, `metrics`, `optim`, `parameter_resolution`, `persistence`, `protocols`, `report` |
| `preflight` | inside its checks: `criteria`, `metrics`, `observations`, `optim`, `parameter_resolution`, `protocols`, `runners`, `targets` |
| `__init__.py` | `config`, `optim`, `report`, `runners` |

Five more rules:

1. No module uses a `_private` name of another part.
2. Another layer of HydroModPy imports only the modules listed under `public`
   in `calibration_layout.yaml` (next section).
3. No re-export: a name is imported from the module that defines it.
4. Calibration reaches a solver only through the generic ports of
   `solver.base` (registry, observables) and the run result
   (`simulation.planning.plan.RunExecutionResult`), never through a backend
   package (`solver.modflow6`, `solver.modflow_nwt`, `solver.modflow_common`,
   `solver.boussinesq`). A backend can then be added or replaced without
   touching calibration. `solver_access` in `calibration_layout.yaml` checks it.
5. One exception: `evaluation/registry.py` names its built-in evaluators by a
   dotted path written as text, and imports one only when a run asks for it.
   Checking that a document names a known evaluator does not import it. So the
   evaluators that read the calibration document can live above `config`
   (`runners/pipeline_evaluator.py`, `metrics/scored_forward.py`), and a
   third-party evaluator joins the same table.

## Tree

```
hydromodpy/calibration/
  __init__.py                  CalibrationConfig, CalibrationEngine, objectives, build_optimizer
  config.py                    the [calibration] schema (Pydantic)
  targets.py  parameter_resolution.py  persistence.py  report.py  preflight.py
  criteria/     base.py (Criterion, requirements)  series.py (METRICS and kernel conventions)
                hydrographic_network_distance.py  registry.py (criterion_for)
  optim/        parameters.py (ParameterSpace, set_by_path)  sampling.py
                objective.py  optimizer.py (protocol, EngineTraits, registry, choose_method)
                method_config.py  engine.py  stopping.py  cache.py  progress_reporter.py
                fosm.py  cost_margin.py  diagnostics.py
    adapters/   one module per search method
  evaluation/   port.py  forward.py  registry.py  forward_registry.py
                analytic_bowl.py  linear_reservoir.py
  protocols/    base.py  registry.py  boilerplate.py  matching_hydrographic_network.py
  observations/ network_source.py  observed_network.py  network_geometry.py
  metrics/      solver_extract.py  composite.py  observed_pairing.py  observable_scoring.py
                scalar.py  series.py (observed series by role)  gauge_snap.py
                downslope_network.py  scored_forward.py
  runners/      cli_runner.py (entry)  document.py (read the TOML)  search.py (one search)
                session_scope.py (open, close, promote)  staged_runner.py  programmatic_runner.py
                trial.py  contracts.py  sandbox.py  verdict.py  materialize.py
                phase_regime.py (steady or transient, as config overrides)
                pipeline_evaluator.py  promotion.py  recap.py  restarts.py  resume.py
                session.py (case name, session directory, frozen config)
                state.py (params-hash context, cache preload)  failure_watch.py
                kept_solves.py (trial solves kept on disk for their promotion)
                worker_pool.py (the trials of parallel > 1 in worker processes)
                prepared_model.py (the checks that need the prepared model)
```

## Template of a search method

One module per method in `optim/adapters/`. No list to edit:
`optim/optimizer.py` walks that folder on the first lookup and imports every
module whose name does not start with `_`.

```python
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace


@register_optimizer("mymethod")
class MyMethod:
    name = "mymethod"
    traits = EngineTraits(max_parameters=None, supports_parallel=False, takes_max_trials=True)

    def __init__(self, space: ParameterSpace, *, max_trials: int = 100) -> None: ...
    def ask(self, n: int = 1) -> list[ParamSuggestion]: ...
    def tell(self, results: list[EvaluationResult]) -> None: ...
    def suggest_next(self) -> ParamSuggestion: ...
    def best(self) -> EvaluationResult | None: ...
    def converged(self) -> bool: ...
```

Its options are a Pydantic model in `optim/method_config.py`, one member of the
`CalibrationMethodConfig` union, so an unknown option is refused when the file
is read rather than inside the adapter.

## How a calibration flows

1. **Load.** `HydroModPyConfig` validates `[calibration]` into
   `CalibrationConfig`. A named protocol is expanded first
   (`protocols.expand_calibration_protocol`), and each parameter name is
   resolved to a config path (`parameter_resolution.resolve_parameter_targets`).
   Validators refuse an unknown criterion, evaluator or forward model here.
   An unknown search method loads, and is refused by the preflight below,
   before anything is prepared. `CalibrationConfig.validate_registry` refuses
   it again when the search starts, and resolves a method left unwritten,
   through `method_for` (`optim.optimizer.choose_method`).
2. **Check.** Every launch, `hmp calibrate`, `hmp run`, `--dry-run`,
   `hmp.calibrate` and `Project.calibrate`, runs `preflight.preflight_launch`
   on the document it runs (`--set`, `--overlay` and `HMP_SET_*` written in),
   each phase with its own overrides: every check, one report, no solve, and
   an error stops the launch before anything is prepared. `hmp config check`
   prints the same findings.
3. **Start.** `runners/cli_runner.py` and `search.py` (one search), `staged_runner.py`
   (phases) or `programmatic_runner.py` (from Python) names the case
   (`runners/session.py`: the stem of the file that carries `[calibration]`,
   unless it writes `[simulation] name` itself), reserves `sessions/<case>/`
   with `reserve_version_dirname`, freezes the resolved document there as
   `config.toml`, then builds the `ParameterSpace`, the optimizer
   (`optim.optimizer.build_optimizer`), the evaluator (`evaluation.registry`)
   and the `CalibrationEngine`.
4. **Prepare once.** `runners/trial.py` prepares the model once: geography,
   mesh and data are built a single time, through the provider registered in
   `runners/contracts.py` by the workflow layer. The provider finds the first
   pipeline step that reads one of the calibrated config paths
   (`earliest_affected_step` of `hydromodpy/workflow/steps/dependencies.py`).
   The steps before it run once and are shared by every trial; the steps from it
   up to the solve and the extraction run again for each trial
   (`run_trial_light`); the persistent steps downstream run only for a promoted
   trial (`promote_prepared_trial`). Right after each preparation, once per
   search or per phase and before the session is reserved,
   `runners/prepared_model.check_the_prepared_model` checks what only the
   prepared model shows: a bound the field refuses, and the drain and
   release-package conductances a network search relies on.
5. **Trial.** The engine asks the optimizer for a point, skips it if its params
   hash is cached (`optim/cache.py`), and hands it to the evaluator. The default
   one, `runners/pipeline_evaluator.py`, sets the values, runs the solver
   (`run_trial_light`), extracts the outputs (`metrics/solver_extract.py`,
   `metrics/composite.py`) and pairs them with the observations
   (`metrics/observed_pairing.py`).
6. **Score.** `optim/objective.py` turns the paired series into one cost with
   the kernels of `criteria/`, block by block, and the engine tells the
   optimizer.
7. **Write.** Each trial goes to `sessions/<case>/trials.jsonl`
   (`persistence.py`), with a number unique in the session across phases and
   restarts. Nothing opens the index: it is rebuilt from the session files.
8. **Promote.** Once per phase, after its last restart, `runners/promotion.py`
   promotes what `save_runs` names: the best trial of the last phase to
   `runs/<case>/`, the directory paired with the session (same version), with
   `lineage` and `checks.calibrated_by` naming the session, the phase and the
   trial; the other kept trials to `sessions/<case>/trials/<n>/`; with
   `promote_phases`, the best of each earlier phase to
   `sessions/<case>/phases/<phase>/best/`. A trial the session may promote
   keeps its solver folder (`runners/kept_solves.py`), and its promotion goes
   on from extraction on that folder instead of solving again. The journal
   line of a promoted trial receives the `sim_id` and the `rel_dir` of its run.
   `hmp campaign promote <case> --trial N` replays a trial after the fact from
   `sessions/<case>/config.toml` and the frozen values of its phase
   (`promote_trial_from_session`; a trial kept under `trials/<n>/` is moved,
   with the seal it was written with); `hmp campaign prune <case> --keep best`
   trashes the other kept trials (`prune_session`). A reopened session
   promotes once more at its end: a trial already written is not written
   again, and the paired `runs/<case>/` is never overwritten; when it holds
   another trial of the session, the new best is reported as a promotion
   failure, the session closes `partial`, and `hmp campaign promote` writes it
   under the next version.
9. **Close.** `session.json` takes the status (`completed`, `partial`,
   `failed`, `aborted`) and the best trial, `outcome.json` the issue,
   `README.md` the summary. A promotion failure closes a completed search
   `partial`, never `failed`. The three runners close their session through
   one scope (`closing_session`): SIGTERM or SIGINT writes `aborted`, marks
   the cut phase and points at the best trial of the last completed phase
   (or of the cut phase) in under a second, then promotes that trial from
   its kept solve when it has one, with `calibrated_by.session_status =
   aborted`; an error of the search writes `failed`. `hmp calibrate --resume`
   reopens the latest session of the case: a phase that completed with the
   same fingerprint is read back (`runners/resume.py`), the cut phase is
   solved again with its trials preloading the cache.
10. **Report.** `report.py` reads the session directory back;
    `display/calibration_report.py` renders it.

## Storage rule

A calibration occupies two sibling directories of one name: `sessions/<case>/`
(what the search evaluated) and `runs/<case>/` (the calibrated run). What a
trial writes depends on `save_runs` (`CalibrationConfig`: `best_n` with
`save_best_n = 1` by default, `all`, or `none`).

- Inside the loop a trial lives in RAM: the aligned simulated series and the
  scalar metrics. `run_trial_light` never writes to the store of runs.
- Every trial leaves one line in `sessions/<case>/trials.jsonl`
  (`results/session/journal.py`), numbered once across phases and restarts.
  `session.json` is the descriptor, `phases/<phase>/session.json` one per
  phase, `outcome.json` the issue, `config.toml` the frozen document the
  promotion replays from. The index is rebuilt from these files; the
  calibration never opens it.
- Zarr and Parquet exist only for promoted trials: the best under
  `runs/<case>/`, the others under `sessions/<case>/trials/<n>/`, each linked
  to its journal line by `sim_id` and `rel_dir`.

The params hash (`optim/cache.py`: SHA-256 of the canonical JSON of the rounded
parameter values and of a context that fingerprints the inputs) keys the cache.
The context holds only what changes the cost of a trial at given values: the
model and its inputs, the outputs, the objective blocks, the scoring window and
what the evaluator reads. The method, its options, the seed, the precision, the
budget and the bounds are outside it, so a search that changes one of them
replays the trials it proposes at values already solved.
With `use_cache = true` (the default) a run preloads the hashes of every
`trials.jsonl` of the project (`runners/state.py:preload_hash_cache`), so a
point evaluated in an earlier session of the same project is not solved again.

## Protocols and phases

A calibration runs as one or more **phases**. A phase says which parameters it
moves, in which flow regime, and against which objective blocks with which
share for each. The search method follows from what is scored: a signed
criterion (`distance_gap`) on one parameter in log space is a zero to find,
searched by bisection; anything else is a cost to minimize, by Nelder-Mead.
That choice applies to a phase and, the same way, to a calibration with no
phases at all (`optim.optimizer.choose_method`, read through
`CalibrationConfig.method_for`). `method` is written only to choose otherwise
(`"cma_es"`, `"optuna"`, `"grid"`, ...). A **protocol** is a named recipe tied
to a publication: it writes the phases of a published method, cites it, and
lets the user set its options but not its sequence. Everything a protocol
does, phases written by hand can say too, and
`hmp calibrate FILE --expand` prints the phases a protocol writes, as TOML to
start from.

One rule links the phases, in declaration order:

> A phase moves the parameters it lists. Every other parameter holds the last
> value an earlier settled phase found for it, or the value of the model
> file when no phase has calibrated it yet. A phase that lists a parameter an
> earlier phase calibrated moves it again, starting from that value when its
> search method accepts a start point.

Blocks are declared once under `[[calibration.objective_blocks]]`. A phase
lists the ones it scores, or gives each a share. Shares are normalized to sum
to one, so `{ hydrograph = 70, network = 30 }` reads as 70 % and 30 % of the
cost. The share of a cost counts the same as an influence only when the costs
are comparable. An efficiency (`nse_log`) is a pure number and a network
distance is in meters, so write `normalize_cost = true` on the network block:
each distance is then divided by the output's `validity_length` (Eq. 4,
`"auto"` = 2 h_obs), and a gap of one validity length costs 1, as much as an
NSE of 0. `normalize_cost` stays refused on the efficiency, already a pure
number.

A spin-up is left out by dates: `window.start` on the phase (or on
`[calibration]`) is the first date scored, for every block alike. A series
keeps its stamps inside the window. A network output reads one state, dated
at the stamp that closes its period: `time = "last"` (the default),
`"first"`, or a date such as `"2002-10-15"`, which reads the period that
holds it. The window has to hold that stamp, and `hmp config check` says so
before any solve when it does not. The old `warmup` and `warmup_periods`
counted samples, so their span followed the time step; `hmp doctor
--fix-config` turns `warmup_periods` into the start date of the window.

Dates can be kept apart from the search with `validation_window = {start, end}`
on `[calibration]`, once for the session. `[metrics] window` minus those dates
is then the default `window`. Each trial is scored on them from the series it
has already simulated, as the `validation.cost` component, and the promoted run
stores it as `checks.calibrated_by.validation_cost` with its period in `windows`.
The cost never reads them. The score uses the blocks that compare a dated record,
so a network block and a steady phase are left out of it. A window that overlaps
a calibration window, leaves no data or falls outside `[metrics] window` is refused.

The declarations the hand-written examples below share (the published
method writes its own objective blocks):

```toml
[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.streams]
support = "network"

[calibration.outputs.streams.map]
complete = "nancon_stream_network.gpkg"

[calibration.outputs.streams.model]
neighbours = "D8"

[calibration.outputs.gauge]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["streams"]

[[calibration.objective_blocks]]
name = "network_share"         # the same gap, counted in validity lengths
metric = "distance_gap"
uses_outputs = ["streams"]
normalize_cost = true

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["gauge"]
```

**K first, then Sy with K fixed.** K alone in steady state against the mapped
network, then Sy alone in transient against the gauge and the network, 2000
left out as spin-up.

```toml
# not checked: fragment, continues the declarations of the first block
[[calibration.phases]]
name = "k_steady"
parameters = ["K"]
regime = "steady"              # one period over [simulation.time], or steady_window
objective_blocks = ["network"]
max_trials = 18

[[calibration.phases]]
name = "sy_transient"
parameters = ["Sy"]            # K holds what k_steady found
regime = "transient"
objective_blocks = { hydrograph = 0.8, network_share = 0.2 }   # two pure numbers
max_trials = 30

[calibration.phases.window]
start = "2001-01-01"           # the network state read, December 2002, lies inside
```

**Both at once.** One phase, both parameters, one regime. Two parameters and
a cost to minimize, so Nelder-Mead; write `method = "cma_es"` for a global
search.

```toml
# not checked: fragment, continues the declarations of the first block
[[calibration.phases]]
name = "k_sy_transient"
parameters = ["K", "Sy"]
regime = "transient"
objective_blocks = ["hydrograph"]
max_trials = 120
```

**In stages, then both together.** A third phase after the two stages above
moves K and Sy again, starting from what they found.

```toml
# not checked: fragment, continues the declarations of the first block
[[calibration.phases]]
name = "k_sy_refine"
parameters = ["K", "Sy"]       # starts at k_steady's K and sy_transient's Sy
regime = "transient"
objective_blocks = ["hydrograph"]
max_trials = 60
```

**Narrower bounds in a later phase.** A phase may write `bounds` for the
parameters it moves, inside the bounds `[calibration.parameters.<name>]` gives:
the first phase searches wide, the refinement searches around what it found. A
phase never widens a search; bounds outside the section's are refused when the
file loads. `hmp calibrate --list-phases` prints them.

```toml
# not checked: fragment, continues the declarations of the first block
[[calibration.phases]]
name = "k_refine"
parameters = ["K"]
bounds = { K = [2e-6, 2e-5] }  # inside the bounds of [calibration.parameters.K]
```

**The published method.** The same first two stages, with the options the
paper leaves open and its citation recorded in the session.

```toml
# not checked: fragment, continues the declarations of the first block
[calibration.protocol]
name = "matching_hydrographic_network"
steady_max_trials = 18
transient_max_trials = 30
```

The transient stage scores itself through an objective block that reads a
`support = "point"` output observing the gauging station, added to
`[calibration.outputs]`, when that station is known from the file alone (one
source, named by `station_ids`, or `[site] gauge`). `--expand` then
shows that output beside the two stages. A file that loads several stations,
or one whose source only discovers its station once the data step runs, keeps
the protocol's older form instead: `variable` and `objective` written on the
phase, naming no output.

**From Python.** The same keys, as dictionaries. A call with phases writes
the document it ran into the project's `sessions/` as `<case>.toml`, so a
Python run can be replayed from a file; the case takes the `[simulation] name`
of the project, else the stem of its file, as on the command line.

```python
import hydromodpy as hmp

project = hmp.Project("examples/projects/04_streamflow_intermittence_in_transient/project.toml")
report = project.calibrate(
    parameters={"K": {"bounds": [1e-7, 1e-3]}, "Sy": {"bounds": [5e-3, 0.35]}},
    outputs={
        "streams": {
            "support": "network",
            "map": {"complete": "nancon_stream_network.gpkg"},
            "model": {"neighbours": "D8"},
        },
        "gauge": {"support": "point", "variable": "discharge", "observes": "NANCON"},
    },
    objective_blocks=[
        {"name": "network", "metric": "distance_gap", "uses_outputs": ["streams"]},
        {
            "name": "network_share",
            "metric": "distance_gap",
            "uses_outputs": ["streams"],
            "normalize_cost": True,
        },
        {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
    ],
    phases=[
        {
            "name": "k_steady",
            "parameters": ["K"],
            "regime": "steady",
            "objective_blocks": ["network"],
            "max_trials": 18,
        },
        {
            "name": "sy_transient",
            "parameters": ["Sy"],
            "regime": "transient",
            "objective_blocks": {"hydrograph": 0.8, "network_share": 0.2},
            "max_trials": 30,
            "window": {"start": "2001-01-01"},
        },
    ],
)
```

A phase takes the search of `[calibration]` key by key: `method`,
`max_trials`, `precision` and `method_options` written in the phase win, then
the section's, then the default (a method chosen from what the phase scores,
`max_trials = "auto"`). A precision of the section reaches only a phase whose
engine stops on one, and not a phase that writes that stopping option itself;
the options of the section reach a phase that runs the section's method, and
`method_options = {}` in a phase states that it takes none.
`hmp calibrate FILE --list-phases` says where each key comes from.

Each phase also says how wide its answer is (`uncertainty`, same keys as
`[calibration.uncertainty]`, which stays the default for every phase). Left
unwritten, the width follows what the phase scores: a phase scored only by
network distances takes one mesh cell, in meters (a stream cannot move by
less); any other phase takes 5 % of its best cost. `cost_margin` writes it
with its unit, `"5%"` of the best cost or `"75 m"` of network distance (a
bare number is refused, and a length only on a search scored by network
distances). `hmp config check` refuses a share on a phase scored only by
network distances. The
interval never moves the calibrated value; it says which values the search
could not tell apart from it.

`hmp calibrate FILE --list-phases` shows, for each phase, the parameters it
moves, the ones it re-opens and from which phase (when it moves a parameter
an earlier phase calibrated, and whether its engine starts from that value),
which method it runs and why, the width of its interval, and for each block
what is compared with what: the simulated quantity and the observed source (a
station of `[data.<family>]`, or a network file). After a phase, the report
gives the share of the cost each block actually took, which differs from the
declared share when the blocks have different units.
`overrides` stays for any other configuration value a phase must change
(a dotted path into the project configuration).

## Where to add what

1. **A search method.** A module in `optim/adapters/` on the template above,
   plus its options model in `optim/method_config.py` added to the
   `CalibrationMethodConfig` union. Test it in
   `tests/unit/calibration/test_optim_adapters_<method>_adapter.py`.
2. **A criterion a TOML can name.** The kernel `(sim, obs) -> float` in
   `criteria/series.py`, its name in `METRICS`, its direction in `METRIC_SENSE`
   (`results/catalog/constants.py`, which turns a score into a cost with
   `cost_of`), and its name in `LOG_METRICS` or `DIMENSIONLESS` when that applies. Add the name to
   `MetricKind` in `config.py`: `test_criteria_series.py`
   keeps the two equal. `criteria/registry.py` builds from `METRICS`, with no
   second list.
3. **An evaluator.** A class with `evaluator_id`, `needs_prepared_model` and
   `evaluate(TrialRequest) -> TrialOutcome` (`evaluation/port.py`). Its
   constructor takes only names from `CONSTRUCTION_OPTIONS`
   (`evaluation/registry.py`). Outside HydroModPy, publish it in the
   `hydromodpy.calibration.evaluator` entry-point group. Inside, put it in
   `evaluation/` if it reads nothing from `config.py`, otherwise beside what it
   uses, and add its dotted path to `_BUILTIN_PATHS`.
4. **A forward model.** A class with `model_id` and
   `simulate(ForwardRequest) -> ForwardOutcome` (`evaluation/forward.py`),
   published in `hydromodpy.calibration.forward_model` or listed in
   `evaluation/forward_registry.py`. A document selects it with
   `evaluator = "scored_forward_model"` and `forward_model = "<id>"`.
5. **A calibration protocol.** A module in `protocols/` with a class that
   satisfies `CalibrationProtocol` (`protocols/base.py`: references,
   deviations, `expand`), an instance in `_PROTOCOLS` of
   `protocols/registry.py`, and its options model in `config.py`.
   `CalibrationProtocolDecl` then becomes a union discriminated on `name`.
6. **A phase option.** The field on `CalibPhaseDecl` in `config.py`, and its
   effect in `runners/staged_runner.py` (`_phase_config`) or, for a model
   setting, in `runners/phase_regime.py`. A protocol that needs it writes it
   into the phases it expands; it never reaches around the phase.
7. **A `[calibration]` field.** The field on its model in `config.py`, with a
   profile and a description. The parameter reference is computed from the
   model at the next documentation build (`tools/docs/field_registry.py`).
   The committed JSON Schema, `docs/source/_static/hydromodpy-schema.json`, is
   compared with the model by `tests/unit/docs/test_docs_config_consistency.py`.

## Key public symbols

- `hydromodpy.calibration.runners.cli_runner.run_calibration_cli`,
  `runners.programmatic_runner.run_calibration_programmatic` and
  `runners.staged_runner`: the three entry points.
- `hydromodpy.calibration.optim.engine.CalibrationEngine`: the ask and tell loop.
- `optim.optimizer.{available_optimizers, build_optimizer, register_optimizer}`:
  the registry of search methods.
- `optim.objective.{Objective, build_objective_from_config}`: the cost.
- `optim.diagnostics.correlated_parameter_pairs`: the parameters a finished search
  moved together, which the report flags. `convergence_rate` fits the decrease of
  the best cost, and no report reads it.
- `metrics.composite.build_metric_extractor`: how the outputs of a trial are
  extracted.

## Layer neighbors

`calibration` imports `core`, `physics`, `data`, `spatial`, `solver`,
`simulation` and `results` (`tests/unit/architecture/layer_matrix.yaml`). It never
imports `display`. The root facade, `config`,
`workflow`, `project` and `cli` import it. `workflow` is reached only through the
provider of `runners/contracts.py`, which the bootstrap fills.

## Reading path

1. This file.
2. `__init__.py` for the public surface.
3. `runners/search.py`, then `optim/engine.py`.
4. `runners/trial.py` for the prepare-once and evaluate-many primitive.
5. One adapter: `optim/adapters/optuna_adapter.py` is the most generic.
6. One case driven from Python: `validation_cases/calibration/recession_hillslope_aquifer/experiment.py`.

## What other layers import

Only these modules, listed under `public` in `calibration_layout.yaml`:
`hydromodpy.calibration`, `config`, `targets`, `parameter_resolution`,
`preflight`, `protocols`, `report`, `optim.parameters`,
`runners.cli_runner`, `runners.document`, `runners.staged_runner`,
`runners.programmatic_runner`, `runners.contracts`.

A model outside HydroModPy joins through two entry-point groups: an
evaluator (`hydromodpy.calibration.evaluator`, written against
`evaluation.port`) or a forward model (`hydromodpy.calibration.forward_model`,
against `evaluation.forward`). Search methods ship with HydroModPy and are not
plugged from outside. A search of one's own runs from Python: an object that
satisfies `Optimizer` (`optim/optimizer.py`: `name`, `ask`, `tell`,
`suggest_next`, `best`, `converged`), handed to
`CalibrationEngine(optimizer=...)` (`optim/engine.py`), with no registration.

## Vocabulary

- **trial**: one run of the model with one set of parameter values.
- **prepared trial** (`TrialContext`): what is built once and reused by every
  trial of a search.
- **evaluator**: turns a trial request into a cost; the unit a document can
  swap (`evaluator = ...`).
- **forward model**: returns simulated outputs only; `scored_forward_model`
  scores them with the document's objective.
- **criterion**, **kernel**: the function that scores one simulated series
  against one observed series; a TOML names it with `metric`.
- **objective block**: one `[[calibration.objective_blocks]]` entry, an output,
  a criterion and a weight. The objective sums the blocks.
- **parameter space**: the parameters with their bounds, search space and sampling.
- **phase**: one search of a calibration: its parameters, regime, objective
  blocks with their shares, and method.
- **protocol**: a named recipe tied to a publication, which writes phases.
- **share**: the weight of an objective block within one phase, normalized to
  sum to one over the blocks of that phase.
- **re-opened parameter**: one a phase moves again after an earlier phase
  calibrated it; the search starts from the earlier value when it can.
- **session**: one calibration of a case on disk, `sessions/<case>/`: its
  journal, its phases and its frozen configuration.
- **case**: the name a calibration file gives its session and its calibrated
  run, the stem of the file that carries `[calibration]`.
- **params hash**: the key that lets a search skip a point it already ran.
- **promotion**: running the pipeline on a trial, from its kept solve when
  there is one, so it gets a run of its own: the best to `runs/<case>/`.
