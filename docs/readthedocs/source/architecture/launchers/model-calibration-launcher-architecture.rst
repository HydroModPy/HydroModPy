Model Calibration Launcher
==========================

Scope
-----

This page documents the launcher-side architecture of
``launchers.model_calibration``.

It is the right entry point when you want to understand:

- how calibration is orchestrated as one first-class launcher workflow,
- how one candidate parameter vector becomes one runnable simulation config,
- where launcher responsibilities stop and the reusable calibration core
  begins.

Architecture role
-----------------

``ModelCalibrationLauncher`` is not a second calibration engine. Its role is to
wrap the generic calibration core around one prepared HydroModPy simulation
workflow.

In practice it owns:

- validation of ``[model_calibration]`` and the linked simulation config,
- preparation of one reusable session rooted on a reference simulation config,
- actualization of candidate parameter values into derived TOML overrides,
- execution of candidate simulations through ``HydroModPyLauncher``,
- extraction of canonical outputs and composite-objective evaluation,
- persistence of iteration history, reruns, distributions, objective maps, and
  reports.

Recommended code path
---------------------

The shortest useful reading path is:

1. ``launchers/model_calibration/launcher.py``
2. ``launchers/model_calibration/runtime.py``
3. ``launchers/model_calibration/config.py``
4. ``launchers/model_calibration/output_selection.py``
5. ``launchers/model_calibration/property_arrays.py``
6. ``hydromodpy/simulation/model_calibration_support.py``
7. ``hydromodpy/analysis/calibration/core/``

Main files and responsibilities
-------------------------------

- ``launcher.py`` owns the public orchestration surface:
  prepare session, run candidate, run calibration, finalize artifacts.
- ``config.py`` validates the launcher-side contract:
  calibrated parameters, requested outputs, objective blocks, and objective
  mapping settings.
- ``runtime.py`` owns the heavy lifting:
  prepared sessions, candidate requests, candidate outcomes, hydraulic support
  preparation, reruns, manifest updates, and timing breakdowns.
- ``config_overrides.py`` turns calibrated parameters into concrete TOML
  override fragments on the simulation-side config tree.
- ``property_arrays.py`` builds reusable runtime-ready hydraulic arrays once
  the target property mapping has been resolved.
- ``output_selection.py`` normalizes heterogeneous runtime and postprocess
  outputs into one canonical objective-facing boundary.
- ``objective_mapping.py`` generates additional objective-surface diagnostics
  from already evaluated or newly proposed candidates.
- ``reporting.py`` persists the human-readable session report.
- ``state.py`` stores the launcher-local mutable runtime state.

Session lifecycle
-----------------

One launcher-managed calibration session follows this chain:

1. Load launcher config and linked simulation config.
2. Prepare one reusable session root with a stable contract signature.
3. Resolve reusable hydraulic support from the reference simulation workflow.
4. Actualize one candidate into one derived TOML override.
5. Run the derived simulation through ``HydroModPyLauncher``.
6. Select canonical outputs and build the composite objective.
7. Persist iteration records and optional diagnostic artifacts.
8. Finalize best reruns, model distributions, objective maps, and reports.

Boundary with the reusable calibration core
-------------------------------------------

The launcher layer should own workflow orchestration and artifact persistence.
The reusable calibration core should own optimization mechanics.

That means:

- ``launchers.model_calibration`` owns how HydroModPy simulations are prepared,
  patched, executed, and harvested;
- ``hydromodpy.analysis.calibration.core`` owns optimization methods,
  parameter sets, objective abstractions, and canonical results;
- ``hydromodpy/simulation/model_calibration_support.py`` is the bridge between
  a prepared simulation runtime and launcher-managed calibration support.

See also
--------

- :doc:`../calibration/calibration-overview`
- :doc:`../calibration/calibration-execution-flows`
- :doc:`../simulation/toml-to-solver-walkthrough`
