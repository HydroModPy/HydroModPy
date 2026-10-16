Comparison of sealed runs
=========================

``hmp report compare`` compares N runs that already finished. It never runs a
simulation and never reads a comparison TOML: the runs to compare are recipes of
one project (``[sites.recipes]``), run like any other case, and the comparison
reads their directories.

.. code-block:: bash

   hmp report compare nancon-mf6 nancon-bouss
   hmp report compare calage_nm calage_tpe --by site
   hmp report compare runs/a runs/b --allow-different-mesh --out ../mesh_study

Positioning
-----------

- The reading lives in ``hydromodpy/analysis/comparison/``; the HTML page in
  ``hydromodpy/reporting/comparison/``. ``reporting`` imports ``analysis``, never
  the reverse.
- A run is read from its directory alone: ``manifest.json`` says what it is,
  ``fields.zarr`` holds its arrays, ``tables.parquet/`` its budget and series,
  ``config.toml`` its frozen configuration
  (``analysis/comparison/runtime/run_source.py``). The project index is not
  opened, and nothing is written into a run.
- The network metrics read a run through ``Run``, opened by ``hmp.open`` on the run
  directory itself, so they need no index either.

References
----------

A reference is a run directory, a run name under ``runs/`` (``nancon_monthly.v2``),
or a recipe: the latest version of every case of that recipe. The first run is the
reference of the differences (``analysis/comparison/runs.py``).

Same case
---------

The runs of one comparison must model the same site and solve on the same mesh:
``identity.site_fingerprint`` and ``identity.mesh_hash`` of their manifests are
equal. A different site is refused, with ``--by site`` named; a different mesh is
refused unless ``--allow-different-mesh`` is passed. The verdict is the
``case_check`` block of ``comparison_manifest.json``: ``status`` (``same_case`` or
``different_mesh_allowed``), the site, its fingerprint and the mesh hash of each run.

Under ``--by site`` the runs of each reference are grouped by site, and each site
held by at least two references gets its own comparison.

Observables
-----------

Each variable of ``--variables`` is mapped at the last step. Without the option,
the head and the depth to the water table are mapped when every run stores them,
or can derive them. When every manifest gives the same outlet
(``site.snapped_outlet``, else the declared outlet), the head and the outlet
discharge are also read there as series. The maps are compared on a shared raster
at the cell size of the reference mesh.

Outputs
-------

The comparison writes under ``summary/report/compare/<refs>/`` of the project, or
under ``--out``; under ``--by site`` each site has its own sub-folder:

.. code-block:: text

   comparison_manifest.json      what was compared, case_check, every artefact, written last
   observables.csv               one row per run, observable, time and value
   comparison_metrics.csv        differences to the reference, one row per run and observable
   comparison_differences.csv    the paired values behind them
   comparison_metrics.json
   numerical_closure_*.csv       water-budget closure of each run, from its budget table
   budget_timeseries_*.csv       budget terms of each run
   timeseries_*.csv              native series of the runs, aligned on time
   comparison_figures/           maps, series, dashboards
   comparison_report.md
   web/index.html                the page, rendered by reporting/comparison

``analysis/comparison/run_comparison.py`` is the only writer and the only reader of
``comparison_manifest.json``.

Where to add what
-----------------

1. **An output.** A module in ``analysis/comparison/exports/``, called from
   ``analysis/comparison/output_pipeline.py``.
2. **A metric.** ``analysis/comparison/metric_diff.py`` for a difference.
3. **A section of the page.** ``reporting/comparison/sections/sections.py``.
