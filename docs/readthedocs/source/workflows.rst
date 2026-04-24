Workflows
=========

Every workflow is reachable as a :class:`~hydromodpy.Project` method and
returns a catalog-backed result.

Simulation
----------

One run::

    project.run(K=5e-5, name="baseline")

Sweep
-----

Enumerate or grid over parameters::

    project.sweep(parameters={"K": [1e-6, 1e-5, 1e-4]}, strategy="enumerate")

Calibration
-----------

Optuna / GP / scipy evaluators driven by the calibration engine::

    project.calibrate(config_path="run_calibration.toml")

Overview
--------

Watershed identity card (data-only, no solver)::

    project.overview()

Mesh
----

Build the catchment mesh without running a simulation::

    project.build_mesh()

Comparison
----------

Run pair or N-variant comparison via the analysis module::

    project.compare(config_path="run_comparison.toml")

Batch
-----

Regional batch across a site catalog::

    project.batch(config_path="regional.toml")
