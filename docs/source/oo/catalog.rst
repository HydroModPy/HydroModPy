Catalog patterns
================

A project handle is convenient for the run loop but unnecessary when
all the caller wants is to read or inspect previously persisted runs.
HydroModPy ships two catalog entry points for that purpose.

hmp.open
--------

:func:`hydromodpy.open` returns a
:class:`hydromodpy.results.catalog.SimulationCatalog` rooted at the
given workspace. It is the read-side complement of
:meth:`Project.run` and mirrors the ``xarray.open_dataset`` intent: one
call, a ready-to-query object.

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/hmp_workspace")
   last = cat.latest()
   da = hmp.read(last, "head")

``cat`` exposes the same query surface as :attr:`Project.runs` but
without the project-name filter: it sees every simulation persisted in
the workspace.

hmp.open_catalog
----------------

:func:`hydromodpy.open_catalog` returns the V1
:class:`hydromodpy.catalog.CatalogFacade`. The facade fronts the three
DuckDB files (``simulations``, ``inputs``, ``projects``) behind matching
namespaces so the call site reads close to the query intent.

.. code-block:: python

   import hydromodpy as hmp

   with hmp.open_catalog("~/proj/naizin") as cat:
       sims = cat.simulations.find(solver="modflow6")
       inputs = cat.inputs.list()
       projects = cat.projects.list()

The context-manager form is preferred: the facade owns DuckDB
connections that should be released on exit. The bare call form is also
supported for short scripts and notebooks.

Notebook pattern
----------------

Catalog and reader compose naturally inside a notebook session:

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/hmp_workspace")
   run = cat.latest()

   head_t0 = hmp.read(run, "head", time=0)
   head_all = hmp.read(run, "head")
   q_out = hmp.read(run, "discharge", sel={"station": "outlet"})

:func:`hmp.read` auto-dispatches the variable name through the field
registry (Zarr), the timeseries table (DuckDB), and the geographic
features table (GeoParquet), so a single call handles the three storage
kinds.

See Also
--------

- :func:`hydromodpy.open` -- workspace-level catalog.
- :func:`hydromodpy.open_catalog` -- V1 catalog facade with namespaces.
- :func:`hydromodpy.read` -- read a variable from a persisted run.
- :func:`hydromodpy.index` -- machine-wide federation of workspaces.
