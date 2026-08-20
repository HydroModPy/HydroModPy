Catalog patterns
================

A project handle is convenient for the run loop but unnecessary when
all the caller wants is to read or inspect previously persisted runs.
HydroModPy ships a single catalog entry point for that purpose.

hmp.open
--------

:func:`hydromodpy.open` returns a
:class:`hydromodpy.results.catalog.Catalog` rooted at the given
project. It is the read-side complement of
:meth:`Project.simulate` and mirrors the ``xarray.open_dataset`` intent:
one call, a ready-to-query object.

By default ``create=False``: the call raises ``FileNotFoundError`` when
no ``.hmp/index.duckdb`` exists in the project. Pass ``create=True`` to
initialise an empty catalog.

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/hmp_workspace/projects/naizin")
   last = cat.latest()
   da = hmp.read(last, "head")

``cat`` is scoped to one project: it sees every run persisted under
that project root and nothing from its neighbours. Querying across
projects is the job of :func:`hmp.index`.

Query surface
-------------

The catalog is the single door. :meth:`cat.find` is the one filtered
entry point and returns a ``RunSet``; an unknown filter key
raises ``ValueError`` listing the valid filters. :attr:`cat.frame`
returns the full ``DataFrame``. Federation across projects lives on
:func:`hmp.index`, which registers one row per project root and
expands a workspace root into the project roots it holds. Inputs are
reached via
:class:`hydromodpy.catalog.InputsNamespace` or the ``hmp data`` CLI.

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/proj/naizin")
   sims = cat.find(solver="modflow6")
   frame = cat.frame
   projects = hmp.index()

Schema discovery and selectors live on the same object:
:meth:`cat.describe`/:meth:`cat.tables`/:meth:`cat.columns`/
:meth:`cat.variables`/:meth:`cat.metrics`/:meth:`cat.stations`, plus
:meth:`cat.latest`/:meth:`cat.best`/:meth:`cat.worst`/:meth:`cat.rank`,
``cat[ref]``, :meth:`cat.resolve`, :meth:`cat.sql`, and
:meth:`cat.read` for the by-id read path.

Notebook pattern
----------------

Catalog and reader compose naturally inside a notebook session:

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/hmp_workspace/projects/naizin")
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

- :func:`hydromodpy.open` -- project-level catalog.
- :func:`hydromodpy.read` -- read a variable from a persisted run.
- :func:`hydromodpy.index` -- machine-wide federation of registered
  projects.
