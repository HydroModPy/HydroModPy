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
| `lumped/` | GR4J, the lumped model that runs in memory, outside the solver registry |
| `criteria/` | how one simulated series is scored against one observed series: the scoring kernels (`METRICS` in `series.py`), their conventions, and the network distance |
| `optim/` | how the search runs: parameter space, objective, optimizer protocol and registry, engine, stopping, params-hash cache, uncertainty (FOSM, tolerance) |
| `optim/adapters/` | the search methods themselves: grid, random, scipy, CMA-ES, Optuna, bisection, GP mapping, DA-MH-GP |
| `persistence.py` | how a session is written: the journal first, then the DuckDB index |
| `report.py` | how a finished session is read back for the report |
| `evaluation/` | what one trial must answer: the evaluator port and the forward-model port, their registries, and the two evaluators that need nothing from the calibration document |
| `config.py` | what the modeller wrote: every `[calibration.*]` table, protocol options included |
| `protocols/` | which published recipe a calibration follows, and how it expands into phases and objective blocks |
| `observations/` | what is observed: the observed stream network, its geometry, network truth files and their cost |
| `metrics/` | how the outputs of one trial are extracted and paired with observations, and the evaluator that scores a forward model |
| `runners/` | how a calibration runs: the three entry points, the phases and what they hand to each other, the trial primitive, the default evaluator, restarts, resume, promotion of the best trials |
| `reporting/` | the diagnostic page of the B0 network validation case |
| `preflight.py` | `hmp calibrate --check`: every check before the first solve |
| `cases/` | two demonstrators kept as regression fixtures |

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
| `reporting` | `observations` |
| `preflight` | inside its checks: `criteria`, `metrics`, `observations`, `optim`, `parameter_resolution`, `runners`, `targets` |
| `__init__.py` | `config`, `optim`, `report`, `runners` |
| `cases` | `__init__.py`, `optim` |

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
  optim/        parameters.py (ParameterSpace, set_by_path)  prior_sampling.py
                objective.py  optimizer.py (protocol, EngineTraits, registry, choose_method)
                method_config.py  engine.py  stopping.py  cache.py  progress_reporter.py
                fosm.py  tolerance.py  diagnostics.py  objective_mapping.py (trace parser for plots)
    adapters/   one module per search method
  evaluation/   port.py  forward.py  registry.py  forward_registry.py
                analytic_bowl.py  linear_reservoir.py
  protocols/    base.py  registry.py  boilerplate.py  matching_hydrographic_network.py
  observations/ network_source.py  observed_network.py  network_geometry.py  network_cost.py
                natural_observations.py  network_transient_truth.py  record.py
  metrics/      solver_extract.py  composite.py  observed_pairing.py  observable_scoring.py
                scalar.py  series.py (observed series by role)  gauge_snap.py
                downslope_network.py  scored_forward.py
  runners/      cli_runner.py  staged_runner.py  programmatic_runner.py
                trial.py  contracts.py  sandbox.py  verdict.py  materialize.py
                phase_regime.py (steady or transient, as config overrides)
                pipeline_evaluator.py  promotion.py  restarts.py  resume.py
                state.py (store and params-hash context)  failure_watch.py
  reporting/    network_transient_html.py  network_transient/
  lumped/  cases/
```

## Template of a search method

One module per method in `optim/adapters/`. No list to edit:
`optim/optimizer.py` walks that folder on the first lookup and imports every
module whose name does not start with `_`.

```python
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits, EvaluationResult, ParamSuggestion, register_optimizer,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace


@register_optimizer("mymethod")
class MyMethod:
    name = "mymethod"
    traits = EngineTraits(max_parameters=None, supports_parallel=False)

    def __init__(self, space: ParameterSpace, *, max_iter: int = 100) -> None: ...
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
   An unknown search method is refused when the run starts
   (`CalibrationConfig.validate_registry`), which also resolves a method left
   unwritten, through `method_for` (`optim.optimizer.choose_method`).
2. **Check.** `hmp calibrate --check` runs `preflight.py`: every check, one
   report, no solve.
3. **Start.** `runners/cli_runner.py` (one search), `staged_runner.py`
   (phases) or `programmatic_runner.py` (from Python) builds the
   `ParameterSpace`, the optimizer (`optim.optimizer.build_optimizer`), the
   evaluator (`evaluation.registry`) and the `CalibrationEngine`.
4. **Prepare once.** `runners/trial.py` prepares the model once: geography,
   mesh and data are built a single time, through the provider registered in
   `runners/contracts.py` by the workflow layer.
5. **Trial.** The engine asks the optimizer for a point, skips it if its params
   hash is cached (`optim/cache.py`), and hands it to the evaluator. The default
   one, `runners/pipeline_evaluator.py`, sets the values, runs the solver
   (`run_trial_light`), extracts the outputs (`metrics/solver_extract.py`,
   `metrics/composite.py`) and pairs them with the observations
   (`metrics/observed_pairing.py`).
6. **Score.** `optim/objective.py` turns the paired series into one cost with
   the kernels of `criteria/`, block by block, and the engine tells the
   optimizer.
7. **Write.** Each trial goes to the session journal, then to the DuckDB index
   (`persistence.py`).
8. **Promote.** `runners/promotion.py` replays the best trials through the full
   pipeline and links each to its simulation id.
9. **Report.** `report.py` reads the session back;
   `hydromodpy/reporting/calibration_report.py` (another layer) renders it.

## Protocols and phases

A calibration runs as one or more **phases**. A phase says which parameters it
moves, in which flow regime, and against which objective blocks with which
share for each. The search method follows from what is scored: a signed
criterion (`distance_gap`) on one parameter in log space is a zero to find,
searched by bisection; anything else is a cost to minimise, by Nelder-Mead.
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
> value an earlier converged phase found for it, or the value of the model
> file when no phase has calibrated it yet. A phase that lists a parameter an
> earlier phase calibrated moves it again, starting from that value when its
> search method accepts a start point.

Blocks are declared once under `[[calibration.objective_blocks]]`. A phase
lists the ones it scores, or gives each a share. Shares are normalised to sum
to one, so `{ hydrograph = 70, network = 30 }` reads as 70 % and 30 % of the
cost. The share of a cost counts the same as an influence only when the costs
are comparable: an efficiency and a distance in metres are not, so
normalise the blocks first (`normalize_cost`) or choose
`[calibration.aggregate] weighting = "error"`.

The declarations the hand-written examples below share (the published
method writes its own objective blocks):

```toml
[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.streams]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"
diagonal_neighbors = true

[calibration.outputs.gauge]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["streams"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["gauge"]
```

**K first, then Sy with K fixed.** K alone in steady state against the mapped
network, then Sy alone in transient against the gauge and the network.

```toml
[[calibration.phases]]
name = "k_steady"
parameters = ["K"]
regime = "steady"              # one period over [simulation.time], or steady_window
objective_blocks = ["network"]
max_iter = 18

[[calibration.phases]]
name = "sy_transient"
parameters = ["Sy"]            # K holds what k_steady found
regime = "transient"
objective_blocks = { hydrograph = 99, network = 1 }   # an efficiency against metres
max_iter = 30
```

**Both at once.** One phase, both parameters, one regime. Two parameters and
a cost to minimise, so Nelder-Mead; write `method = "cma_es"` for a global
search.

```toml
[[calibration.phases]]
name = "k_sy_transient"
parameters = ["K", "Sy"]
regime = "transient"
objective_blocks = ["hydrograph"]
max_iter = 120
```

**In stages, then both together.** A third phase after the two stages above
moves K and Sy again, starting from what they found.

```toml
[[calibration.phases]]
name = "k_sy_refine"
parameters = ["K", "Sy"]       # starts at k_steady's K and sy_transient's Sy
regime = "transient"
objective_blocks = ["hydrograph"]
max_iter = 60
```

**The published method.** The same first two stages, with the options the
paper leaves open and its citation recorded in the session.

```toml
[calibration.protocol]
name = "matching_hydrographic_network"
steady_max_iter = 18
transient_max_iter = 30
```

The transient stage scores itself through an objective block that reads a
`support = "point"` output observing the gauging station, added to
`[calibration.outputs]`, when that station is known from the file alone (one
source, named by `station_ids` or `observed_station_id`). `--expand` then
shows that output beside the two stages. A file that loads several stations,
or one whose source only discovers its station once the data step runs, keeps
the protocol's older form instead: `variable` and `objective` written on the
phase, naming no output.

**From Python.** The same keys, as dictionaries. The call writes the document
it ran into the project's `sessions/` (named `<timestamp>-python-<hex>.toml`),
so a Python run can be replayed from a file.

```python
import hydromodpy as hmp

project = hmp.Project("examples/projects/04_streamflow_intermittence_in_transient/project.toml")
report = project.calibrate(
    parameters={"K": {"bounds": [1e-7, 1e-3]}, "Sy": {"bounds": [5e-3, 0.35]}},
    outputs={
        "streams": {"support": "network", "stream_geometry_path": "nancon_stream_network.gpkg",
                    "diagonal_neighbors": True},
        "gauge": {"support": "point", "variable": "discharge", "observes": "NANCON"},
    },
    objective_blocks=[
        {"name": "network", "metric": "distance_gap", "uses_outputs": ["streams"]},
        {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
    ],
    phases=[
        {"name": "k_steady", "parameters": ["K"], "regime": "steady",
         "objective_blocks": ["network"], "max_iter": 18},
        {"name": "sy_transient", "parameters": ["Sy"], "regime": "transient",
         "objective_blocks": {"hydrograph": 99, "network": 1}, "max_iter": 30},
    ],
)
```

Each phase also says how wide its answer is (`uncertainty`, same keys as
`[calibration.uncertainty]`, which stays the default for every phase). Left
unwritten, the width follows what the phase scores: a phase scored only by
network distances takes one mesh cell, in metres (a stream cannot move by
less); any other phase takes 5 % of its best cost. `hmp calibrate --check`
refuses `mode = "relative"` on a phase scored only by network distances. The
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
   `tests/unit/calibration/test_<method>_adapter.py`.
2. **A criterion a TOML can name.** The kernel `(sim, obs) -> float` in
   `criteria/series.py`, its name in `METRICS`, and in `HIGHER_IS_BETTER`,
   `LOG_METRICS` or `DIMENSIONLESS` when that applies. Add the name to
   `MetricKind` in `config.py`: `test_metric_kind_matches_the_registry.py`
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
   profile and a description. Then run `python -m tools.doc_config` and commit
   the regenerated reference with the change:
   `tests/unit/docs/test_docs_config_consistency.py` compares them.

## What other layers import

Only these modules, listed under `public` in `calibration_layout.yaml`:
`hydromodpy.calibration`, `config`, `targets`, `parameter_resolution`,
`preflight`, `protocols`, `report`, `reporting`,
`reporting.network_transient_html`, `optim.parameters`,
`runners.cli_runner`, `runners.staged_runner`,
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
- **parameter space**: the parameters with their bounds, transform and prior.
- **phase**: one search of a calibration: its parameters, regime, objective
  blocks with their shares, and method.
- **protocol**: a named recipe tied to a publication, which writes phases.
- **share**: the weight of an objective block within one phase, normalised to
  sum to one over the blocks of that phase.
- **re-opened parameter**: one a phase moves again after an earlier phase
  calibrated it; the search starts from the earlier value when it can.
- **session**: one calibration run on disk, its journal and its index rows.
- **params hash**: the key that lets a search skip a point it already ran.
- **promotion**: replaying a best trial through the full pipeline, so it gets
  a simulation of its own.
