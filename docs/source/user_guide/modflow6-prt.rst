MODFLOW 6 PRT Particle Tracking
===============================

Use ``transport/modflow6prt`` when the question is advective travel paths or
travel time in a MODFLOW 6 flow field. This is particle tracking, not a
concentration-transport solve. For concentration, use ``transport/modflow6gwt``.

Execution Model
---------------

HydroModPy runs PRT as a downstream transport process:

1. solve a ``flow/modflow6`` GWF model;
2. attach a MODFLOW 6 PRT model to that flow model through a ``GWF6-PRT6``
   exchange;
3. release particles from the configured cells;
4. let MODFLOW 6 PRT integrate their pathlines through the flow field;
5. read the PRT track output into the HydroModPy results store.

Particles are independent tracers. They do not change the flow solution and do
not interact with each other. The current HydroModPy integration supports
forward tracking on MODFLOW 6 DISV-style meshes.

File Handoff and Direct Reads
-----------------------------

With the current FloPy/external-executable workflow, MODFLOW 6 writes PRT track
outputs to disk. The PRT Output Control package exposes binary ``TRACK`` and CSV
``TRACKCSV`` files, and user-selected output times are supplied through
``TRACKTIMES``. HydroModPy therefore cannot receive pathlines directly as Python
objects from the running ``mf6`` process.

The implemented data path is:

1. MODFLOW 6 writes ``*.trk.csv`` and optionally ``*.trk`` in the solver scratch
   directory;
2. ``Modflow6PrtOutputAdapter`` parses the CSV track file;
3. HydroModPy stores vectorized arrays under ``pathlines/`` in the run Zarr
   store:

   - ``pathlines/x``;
   - ``pathlines/y``;
   - ``pathlines/z``;
   - ``pathlines/time``;
   - optional status and termination-reason arrays.

A more direct plotting path is also available for reports that do not need the
catalogued Zarr arrays: the shared CSV parser can feed an HTML report directly
from ``*.trk.csv``. That avoids a second Zarr read for a one-off page, but it
still consumes a MODFLOW 6 track file because the solver is an external
executable. Avoiding the file boundary entirely would require a different
execution architecture, such as an in-process MODFLOW 6 library binding or a
dedicated streaming callback; that is not how HydroModPy currently runs MODFLOW
6.

Minimal TOML Pattern
--------------------

Declare the flow process first, then the PRT process:

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [[simulation.process]]
   id = "prt_main"
   type = "transport"
   solvers = ["modflow6_prt"]

   [simulation.results]
   keep_solver_files = true

   [transport.modflow6prt.parameters]
   release_zone = "domain_nonriver"
   upstream_top_quantile = 0.88
   track_dir = "forward"
   porosity = 0.01
   local_z = 0.5
   max_particles = 300
   release_times_days = [0.0]
   track_time_step_days = 2.0
   stop_time_days = 3650.0
   stop_travel_time_days = 3650.0
   extend_tracking = true
   dry_tracking_method = "drop"
   exit_solve_tolerance = 1.0e-10
   write_track_csv = true
   write_track_binary = true

The demonstrator in
``examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_steady_mf6_prt_pathlines.toml``
uses this pattern on the Nancon DISV mesh. ``keep_solver_files = true`` is not
required for catalogued Zarr extraction, but it keeps the raw ``*.trk.csv`` file
available for direct inspection and report generation.

Release Zones
-------------

The first implementation supports a small set of deterministic release-zone
selectors:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Zone
     - Meaning
   * - ``domain``
     - All active cells.
   * - ``domain_nonriver``
     - Active cells excluding river-support cells, spread over the modeled
       domain when ``max_particles`` is smaller than the selected zone.
   * - ``upstream``
     - Active cells above the configured top-elevation quantile.
   * - ``upstream_nonriver``
     - Upstream cells excluding river-support cells. This is useful for testing
       hillslope-to-river travel paths without releasing directly on the river.
   * - ``river``
     - River-support cells.
   * - ``outlet``
     - Low-elevation river cells when possible, otherwise low-elevation active
       cells.
   * - ``custom``
     - Explicit zero-based DISV cell ids from ``particle_cell_ids``.

Tracking-Time Discretization
----------------------------

Two mechanisms control stored pathline density:

``track_times_days``
   Explicit list of user tracking output times.

``track_time_step_days``
   Convenience spacing used when ``track_times_days`` is omitted. HydroModPy
   expands it into regular tracking output times from zero to
   ``stop_time_days``.

Increasing tracking-time density does not change the underlying GWF flow solve.
It asks PRT to report more intermediate pathline positions, so the stored and
plotted pathlines look smoother. It can increase CSV/Zarr size.

Velocity and Porosity
---------------------

PRT advective speed depends on the flow field and the porosity used by the PRT
MIP package. In HydroModPy, ``porosity`` can be set explicitly as a uniform
value. When it is omitted, positive specific yield values from the flow model are
used where available. Lower porosity increases pore velocity for the same Darcy
flux, so particles travel farther in the same simulation time.

Version Requirements
--------------------

Use a recent MODFLOW 6 executable with PRT support. The Nancon PRT demonstrator
has been verified with MODFLOW 6.7.0. If HydroModPy resolves an older cached
``mf6`` binary, set an explicit path:

.. code-block:: toml

   [modflow6.runtime]
   mf6_executable_name = "mf6"

References
----------

- MODFLOW 6 PRT Output Control: https://modflow6.readthedocs.io/en/stable/_mf6io/prt-oc.html
- MODFLOW 6 PRT release package: https://modflow6.readthedocs.io/en/latest/_mf6io/prt-prp.html
- MODFLOW 6 PRT migration guide: https://modflow6.readthedocs.io/en/latest/_migration/mf6_6_0_prt_migration_guide.html
- MODFLOW 6 releases: https://github.com/MODFLOW-USGS/modflow6/releases
