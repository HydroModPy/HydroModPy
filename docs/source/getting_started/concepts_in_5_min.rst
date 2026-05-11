Concepts in 5 minutes
=====================

.. page-badges::
   :difficulty: beginner
   :time: 5 min

If you have never used HydroModPy before, read this page first. It introduces
the five core concepts that the rest of the documentation assumes you have
already met. No code, no configuration: just the mental model.

.. contents::
   :local:
   :depth: 1

Project
-------

A *project* is a self-contained workspace describing one modelling effort:
the catchment under study, the data layers attached to it, the workflow
family in use, and the persistence layout. A project corresponds to one
HydroModPy configuration tree (a Pydantic ``HydroModPyConfig``) that you
edit, version, and replay.

Analogy: think of a project the way a notebook power user thinks of a
notebook server, or the way a GIS user thinks of a QGIS project file. It
keeps every input, parameter, and intermediate output linked so the work
is reproducible.

Run
---

A *run* is one execution of a project against a specific scenario. The
project supplies the catchment, data, and solver setup; the run captures
the actual instance: which time window, which forcings, which solver
backend, and the resulting outputs.

Analogy: project is the recipe, run is the cooked meal. Several runs can
share the same recipe but differ on a single ingredient (a calibration
parameter, a forcing dataset, a solver backend).

Workflow
--------

A *workflow* is a named family of runs that share a goal: simulation,
comparison, calibration, validation, etc. The workflow tells HydroModPy
which steps to chain (data extraction, mesh build, solver invocation,
post-processing) and what to persist along the way.

Analogy: a workflow is a pipeline template. The same template can be
applied to many catchments and produces consistent, comparable outputs.

Catchment
---------

A *catchment* is the geographic and hydrologic unit at the centre of every
HydroModPy model: a watershed delimited by an outlet, with topography,
geology, hydrography, and forcing layers attached. HydroModPy specialises
in *shallow groundwater* at catchment scale, so the catchment is what
constrains domain extent, mesh refinement, and boundary conditions.

Analogy: a catchment is to HydroModPy what a basemap is to a GIS workflow:
the spatial reference everything else is anchored on.

Solver
------

A *solver* is the numerical engine that turns the model into a flow field
or hydrograph. HydroModPy currently wraps four solvers: MODFLOW 6,
MODFLOW-NWT, Boussinesq, and GR4J. Each solver lives behind a uniform
adapter, so the same project can target several backends and the
comparison workflow can quantify the differences.

Analogy: think of solvers as different physics engines for the same scene.
The catchment, the data, and the workflow stay the same; the solver
chooses how the equations are approximated and integrated in time.

Where to go next
----------------

- :doc:`choose-your-first-workflow` to pick the workflow family that
  matches your goal.
- :doc:`cli-quickstart` to scaffold a project and trigger a first run from
  the command line.
- :doc:`../user_guide/index` for the operational guide once the concepts
  above feel familiar.
