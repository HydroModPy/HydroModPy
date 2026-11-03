Comparison of sealed runs
=========================

``hmp report compare`` compares runs that already finished. It never runs a simulation and
reads no comparison TOML: the runs to compare are recipes of one project (``[sites.recipes]``),
run like any other case. All the code is one file, ``analysis/comparison/compare.py``, which
reads every run through the public ``Run`` API.

.. code-block:: bash

   hmp report compare nancon-mf6 nancon-bouss
   hmp report compare calage_nm calage_tpe --by site
   hmp report compare runs/a runs/b --variables watertable_depth --out ../mesh_study

From Python, ``hmp.compare(["nancon-mf6", "nancon-bouss"])`` gives the same tables without
writing anything, and ``Comparison.write`` writes them.

References
----------

A reference is a run directory, a run name under ``runs/`` (``nancon_monthly.v2``), or a recipe:
the latest version of every case of that recipe. The first run is the reference of the
differences.

What is refused
---------------

A comparison stops with a message when the runs model different sites, when they share no date,
and when steady and transient runs are mixed. A steady run has no date that compares, so two
steady runs always compare.

How values are paired
---------------------

A stamp closes its period. Two series are compared on the whole periods that every run covers,
at the coarsest step among them, each value averaged over the period and weighted by duration.
So a daily run and a monthly run compare on the months, and a month that one run covers in part
is left out.

Two maps are compared at the last date all the runs share, per unit of surface. When no date is
shared the table is empty. On another mesh, each cell of the reference reads the nearest cell of
the other run, and no further than one cell size. ``same_mesh`` and ``n`` say what was compared.

Outputs
-------

The folder is ``summary/report/compare/<refs>/`` of the project, or ``--out``. Under ``--by site``
each site has its own sub-folder, and ``by_site.csv`` joins their scores.

.. code-block:: text

   README.md         the reference, the dates, every table and figure
   runs.csv          what each run is, with its budget_pct
   parameters.csv    the parameters that differ
   scores.csv        the score of each run at its gauge, its window and its samples
   budget.csv        the mean net flow of each term, zone by zone
   network.csv       overlap and distance between the cells that flow and each mapped network
   series.csv        the differences of each stored series to the reference
   maps.csv          the differences of each map to the reference
   *.png             one figure per series, one map per variable with its difference

The zones of ``budget.csv`` are never added, because the catchment holds water the domain already
counts. Its term ``residual`` sums the others: near zero on the domain, and on a catchment it also
holds the lateral exchange.

Where to add what
-----------------

A new table is one function in ``compare.py``, one line in ``compare``, and one test in
``tests/unit/analysis/comparison/test_compare.py``. Nothing is computed here that ``Run`` can
answer, and no unit is converted: a quantity stays as the run stores it.
