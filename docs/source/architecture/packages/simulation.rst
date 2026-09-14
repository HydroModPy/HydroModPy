simulation
==========

``hydromodpy.simulation`` orchestrates one simulation from validated
configuration to ingested results. It splits planning (declarative
``SimulationPlan`` of ``ProcessRun`` units) from execution
(``SimulationRunner``) and post-run extraction.

Sub-modules
-----------

- ``simulation/planning/`` -- ``SimulationPlanner.build()`` resolves
  ``[[simulation.process]]`` declarations into an immutable
  ``SimulationPlan`` containing one ``ProcessRun`` per
  ``(process_id, solver_name)`` pair. Backward-only dependency
  resolution through ``provider.required_bindings()``.
- ``simulation/execution/`` -- ``SimulationRunner.execute(plan, ctx,
  callbacks)`` iterates the plan, ensures the matching process
  context is available, and delegates each run to the registered
  solver adapter.
- ``simulation/extraction/`` -- post-run hook
  (``post_run_results()``) that ingests solver outputs into the
  catalog. Four steps: ``extract_run_outputs``,
  ``derive_run_outputs``, ``auto_export_results``,
  ``cleanup_solver_outputs``.
- ``simulation/adapters/`` -- backend-agnostic helpers (transport
  adapters, display postprocess). Different from
  ``solver/<backend>/adapters/`` which are backend-specific.

Plan and run units
------------------

.. code-block:: python

   @dataclass(frozen=True)
   class SimulationPlan:
       name: str
       description: str
       runs: tuple[ProcessRun, ...]

   @dataclass(frozen=True)
   class ProcessRun:
       id: str               # for example "flow_main::modflownwt"
       process_id: str
       process_type: str     # "flow", "transport", ...
       solver: str           # "modflownwt", "modflow6", "boussinesq", ...
       depends_on: tuple[str, ...]   # other ProcessRun ids

A single TOML such as ``flow_main [modflownwt] + transport_main
[modpath, mt3dms]`` expands into three ordered runs with the
implicit ``depends_on`` set.

Extraction pipeline
-------------------

After each ``execute``, ``post_run_results()``:

1. Calls registered base extractors (``extract_run_outputs``) that
   convert solver files (HDS, CBC, etc.) into NumPy / Pandas
   payloads.
2. Computes derived outputs (``derive_run_outputs``).
3. Triggers auto-export (``auto_export_results``: Zarr fields, CSV
   tables, JSON manifests).
4. Cleans up scratch files (``cleanup_solver_outputs``).

Derivation helpers live under
``simulation/extraction/derivation/``: ``base.py`` (Protocol),
``observation_ingest.py``, ``catchment_aggregation.py``,
``derived.py``. They register through the solver-output-adapter
registry so each backend can ship its own extractor.

Key public symbols
------------------

- ``hydromodpy.simulation.planning.planner.SimulationPlanner``
- ``hydromodpy.simulation.planning.plan.{SimulationPlan, ProcessRun}``
- ``hydromodpy.simulation.execution.runner.SimulationRunner``
- ``hydromodpy.simulation.extraction.post_run.post_run_results``
- ``hydromodpy.calibration.runners.trial.{prepare_trials,
  run_trial_light, promote_trial}`` (used by calibration).

Recommended reading path
------------------------

1. ``hydromodpy/simulation/README.md``
2. ``hydromodpy/simulation/planning/planner.py``
3. ``hydromodpy/simulation/planning/plan.py``
4. ``hydromodpy/simulation/execution/runner.py``
5. ``hydromodpy/simulation/extraction/post_run.py``
6. ``hydromodpy/calibration/runners/trial.py`` for the
   ``prepare-once / evaluate-many`` primitive used by calibration.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``physics``, ``spatial``,
  ``data``, ``simulation``.
- Allowed sources: ``solver``, ``calibration``, ``config``,
  ``workflow``, ``project`` and ``cli``.

See also
--------

- :doc:`/architecture/simulation/comparison-workflow` for the
  comparison launcher built on top of this stack.
- :doc:`/architecture/simulation/toml-to-solver-walkthrough` for the
  step-by-step config-to-solver path.
- :doc:`solver` for the registry that the planner queries.
- :doc:`workflow` for the pipeline steps that wrap
  ``SimulationRunner``.
