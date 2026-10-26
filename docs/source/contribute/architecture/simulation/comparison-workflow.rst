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
   hmp report compare nancon-mf6 nancon-bouss --budget-zone catchment

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

The three series ``head_domain_low``, ``head_domain_mid`` and ``head_domain_high`` draw the head
of one cell for each third of the active cells, sorted by surface elevation: the median cell of
the lower, middle and upper third. The cells and their elevation come from the reference run,
or from the first run that has a head map. The elevation is ``mesh/topography`` of its
``fields.zarr``, else the top of ``mesh/z_interfaces``. A run whose head map has another cell
count is left out. When the run stores no elevation, no figure is drawn and
``head_domain_figures_skipped.json`` says why
(``reporting/comparison/domain_heads.py``).

Budget zone
-----------

A run stores a budget row for the model domain, and one for the delineated catchment when its
solver writes it (the basin of D, whole cells). The budget exports add up one zone, because the
catchment row counts water that the domain row already counts. ``--budget-zone domain`` is the
default, and ``--budget-zone catchment`` adds up the catchment rows. ``budget_timeseries_long.csv``
and ``budget_timeseries_wide.csv`` carry a ``budget_zone`` column, and the numerical closure reads
the same rows. A run with no row in the zone gives nothing, and a warning says so. A Boussinesq
state is summed over its whole mesh, which is the model domain and has no catchment zone. It
enters the domain export only, and a catchment export leaves it out with a warning.

On example 04 the mean recharge of the export was 2.02 m3/s with the two zones added, 54 % above
the domain value. It is 1.31 m3/s for the domain and 0.71 m3/s for the catchment. The three budget
figures of the comparison name their zone in the title.

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
   budget_timeseries_*.csv       budget terms of each run, one zone, with a budget_zone column
   timeseries_*.csv              native series of the runs, aligned on time
   comparison_figures/           maps, series, dashboards
   head_domain_figures_skipped.json  why the head series by elevation are missing, if they are
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
