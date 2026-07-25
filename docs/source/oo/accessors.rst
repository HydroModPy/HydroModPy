Accessors
=========

A :class:`hydromodpy.project.Project` exposes two accessor properties
that scope catalog queries and data introspection to the current
project. They keep the facade surface small while staying explicit at
the call site.

project.data
------------

:attr:`Project.data` returns a
:class:`hydromodpy.project.accessors.ProjectDataAccessor`. It lists the
input-data variables already loaded for the project and reports the ones
still missing from the declared plan.

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project("project.toml") as p:
       df = p.data.list()          # variables loaded in cache
       todo = p.data.missing()     # variables declared but not loaded

Use this when a workflow step complains about a missing variable, or to
confirm that a manual ``project.load_data(types=...)`` covered the
expected set.

project.runs
------------

:attr:`Project.runs` returns a
:class:`hydromodpy.project.accessors.ProjectRunsAccessor`. It wraps the
project's :class:`~hydromodpy.results.catalog.Catalog` and
pre-filters every query by the current project name.

The accessor exposes four common queries:

- :meth:`~hydromodpy.project.accessors.ProjectRunsAccessor.list`
  returns a DataFrame summary of every persisted run for the project.
- :meth:`~hydromodpy.project.accessors.ProjectRunsAccessor.find`
  filters by metadata (``solver``, ``status``, run name, etc.) and
  returns a list of :class:`~hydromodpy.results.run.Run`.
- :meth:`~hydromodpy.project.accessors.ProjectRunsAccessor.latest`
  returns the most recent :class:`~hydromodpy.results.run.Run` or
  ``None`` when the project has no recorded run yet.
- :meth:`~hydromodpy.project.accessors.ProjectRunsAccessor.best`
  selects the run that minimises a metric stored in the catalog.

.. code-block:: python

   with hmp.Project("project.toml") as p:
       p.simulate(Sy=0.05, name="probe-1")
       p.simulate(Sy=0.08, name="probe-2")

       last = p.runs.latest()
       baselines = p.runs.find(name="probe-1")
       best = p.runs.best("nse")

The accessor returns full :class:`~hydromodpy.results.run.Run` objects,
not just identifiers, so the caller can chain into ``run.field(...)``,
``run.timeseries(...)`` or ``hmp.read(run, "head")``.

See Also
--------

- :class:`hydromodpy.results.run.Run` -- per-simulation result view.
- :doc:`catalog` -- workspace-wide catalog access without a Project.
