Nançon Tutorial
================

.. page-badges::
   :difficulty: beginner
   :time: 45 min
   :tags: install, data, transient

This page starts from an empty machine and ends with a complete monthly
transient MODFLOW 6 simulation of the Nançon catchment, GeoTIFF exports
included. It builds the config in five small files, each inheriting from
the previous one through ``base_config``, so you see exactly what each new
section buys you.

.. important::

   Follow this page top to bottom on a machine that has never run
   HydroModPy. If a workspace already exists and you only want one
   end-to-end case, :doc:`simulation-walkthrough` is shorter.

What this tutorial teaches
---------------------------

- Install HydroModPy and fetch the MODFLOW solver binaries.
- Scaffold a workspace and prove it works with the bundled demo before any
  real data is involved.
- Bring one real catchment's data onto your machine by hand, the honest gap
  before a dedicated command exists.
- Build a config from nothing to a monthly transient run with exports,
  through five layered files and the ``base_config`` merge rules.
- Try a variation with ``--overlay`` and ``--set`` instead of writing a
  sixth file.
- Know where calibration and visualization pick up once this page stops.

1. Install HydroModPy
----------------------

.. code-block:: bash

   pip install --pre hydromodpy

``--pre`` is required while HydroModPy is a pre-1.0 release series; see
:doc:`../install` for optional extras and system dependencies.

2. Fetch the MODFLOW solvers
------------------------------

Solver binaries download on first use, but fetching them eagerly makes the
first run below fully offline:

.. code-block:: bash

   hmp install-binaries

Running it again is a no-op once the binaries are cached; add ``--upgrade``
to force a re-download.

3. Create a workspace
------------------------

A workspace owns the shared input-data cache and hosts one or more
projects:

.. code-block:: bash

   hmp workspace init ~/hydromodpy

It creates:

.. code-block:: text

   ~/hydromodpy/
   ├── workspace.toml   name, contact, licence, geographic scope
   ├── data/            one folder per variable (24 folders), each with a
   │                    README and one example file per accepted format
   └── projects/
       └── example/     a ready-to-run synthetic demo project

4. Run the bundled demo
--------------------------

Before touching any real data, confirm the install works:

.. code-block:: bash

   hmp run ~/hydromodpy/projects/example/run_demo.toml

This finishes in well under a minute on a cached solver install, and prints
``Run completed: demo [<id>] ...`` on success. If it fails, run
``hmp doctor`` before going further.

5. Get the Nançon data onto your machine
-------------------------------------------

.. note::

   There is no dedicated command for this step yet, so the bridge below is
   manual: five files to place in ``data/<variable>/``, by hand. A future
   command (planned as something like ``hmp example add``) will replace
   this section; until it ships, this is the working path, and it stays
   correct once that command lands, since it fetches the same files into
   the same folders.

Download each file into the matching ``data/<variable>/`` folder of the
workspace you just created. The DEM is 90 MiB; the other four are small.

.. code-block:: bash

   D=https://raw.githubusercontent.com/HydroModPy/HydroModPy/v2.0.0a1/examples/data

   curl -L -o ~/hydromodpy/data/dem/DEM_armorican_massif.tif "$D/dem/DEM_armorican_massif.tif"
   curl -L -o ~/hydromodpy/data/hydrography/nancon_stream_network.gpkg "$D/hydrography/nancon_stream_network.gpkg"
   curl -L -o ~/hydromodpy/data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv \
       "$D/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv"
   curl -L -o ~/hydromodpy/data/recharge/recharge_custom_NANCON_20000101_20021231_M.csv \
       "$D/recharge/recharge_custom_NANCON_20000101_20021231_M.csv"
   curl -L -o ~/hydromodpy/data/runoff/runoff_custom_NANCON_20000101_20021231_M.csv \
       "$D/runoff/runoff_custom_NANCON_20000101_20021231_M.csv"

.. list-table::
   :header-rows: 1
   :widths: 30 25

   * - File
     - Goes into
   * - ``DEM_armorican_massif.tif`` (90 MiB)
     - ``data/dem/``
   * - ``nancon_stream_network.gpkg``
     - ``data/hydrography/``
   * - ``hydrometry_custom_NANCON_19820201_20220125_D.csv``
     - ``data/hydrometry/``
   * - ``recharge_custom_NANCON_20000101_20021231_M.csv``
     - ``data/recharge/``
   * - ``runoff_custom_NANCON_20000101_20021231_M.csv``
     - ``data/runoff/``

Then fetch the five step configs into their own project folder:

.. code-block:: bash

   B=https://raw.githubusercontent.com/HydroModPy/HydroModPy/v2.0.0a1/examples/projects/04_streamflow_intermittence_in_transient

   mkdir -p ~/hydromodpy/projects/04_nancon_tutorial
   for f in step1_minimal step2_local_data step3_api_data step4_transient step5_export; do
       curl -L -o ~/hydromodpy/projects/04_nancon_tutorial/$f.toml "$B/$f.toml"
   done

6. The five-step staircase
-----------------------------

Each file below adds exactly one thing to its parent, declared through
``base_config``. Tables merge key by key, a list replaces the parent's
list, and ``<key>__append`` adds to it instead of replacing it; a bare
``<key>__delete = true`` drops an inherited key outright.

step1_minimal.toml — run ``nancon_step1_minimal``, no ``base_config``
   The shortest config that runs to completion on the Nançon catchment:
   steady state, the local DEM, one homogeneous ``K``, and a drainage
   boundary. Nothing here is optional; this is the floor.

   .. code-block:: bash

      hmp run ~/hydromodpy/projects/04_nancon_tutorial/step1_minimal.toml

step2_local_data.toml — run ``nancon_step2_local``, ``base_config = "step1_minimal.toml"``
   Adds the mapped stream network and the burn, from the local files you
   just downloaded. Still steady. Compare the drainage pattern against
   step 1 to see what the mapped network changes.

step3_api_data.toml — run ``nancon_step3_api``, ``base_config = "step1_minimal.toml"``
   The same model as step 2, but the hydrography comes from the BD TOPAGE
   API and the hydrometry from Hub'Eau instead of local files. It is a
   **sibling** of step 2, not a child: both inherit only from step 1, and
   both should produce a comparable network from two different sources.
   Running it needs network access; step 2 does not.

step4_transient.toml — run ``nancon_step4_transient``, ``base_config = "step2_local_data.toml"``
   Switches to monthly transient, 2000-2002, with storage and the observed
   recharge and runoff forcing. This is the complete Nançon simulation,
   with no calibration: the parameters are still the assumed values from
   step 1, not fitted ones.

step5_export.toml — run ``nancon_step5_export``, ``base_config = "step4_transient.toml"``
   Adds a declarative ``[export]`` and a ``[display]`` figure list, four
   ``base_config`` levels deep. Run this last:

   .. code-block:: bash

      hmp run ~/hydromodpy/projects/04_nancon_tutorial/step5_export.toml

   A format toggle such as ``geotiff = true`` writes one file per variable
   that ``[export.variables]`` leaves active, not one file, so this run
   produces six artifacts under ``share/nancon_step5_export/``:

   .. code-block:: text

      head_t33.tif                  the simulated head, October 2002
      watertable_elevation_t33.tif  the three derived fields, same instant
      watertable_depth_t33.tif
      seepage_mask_t33.tif
      timeseries.csv                every series, all 36 steps
      fields_2000_2002.nc           the explicit [[export.artifacts]] entry

   ``netcdf``, ``vtu``, ``shapefile`` and ``package`` are toggles beside
   ``geotiff``; ``[[export.artifacts]]`` names one file instead, its format
   taken from the destination extension, and is the only form that writes
   several timesteps into one file. The four ``[display]`` figures land in
   the run's ``figures/`` directory; use ``hmp viz show`` (section 7) to
   render any other registered figure for this run on demand.

Try a variation without writing a file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``--overlay`` merges an extra TOML payload after the ``base_config`` chain;
``--set`` overrides one dotted path after that. Together they let you try a
change without saving a sixth step file:

.. code-block:: bash

   cat > /tmp/wetter_aquifer.toml <<'EOF'
   [flow.param.Sy.field]
   value = 0.08
   EOF

   hmp run ~/hydromodpy/projects/04_nancon_tutorial/step4_transient.toml \
       --overlay /tmp/wetter_aquifer.toml \
       --set flow.param.K.field.value=1e-4

This runs step 4 with a higher specific yield from the overlay and a
higher ``K`` from ``--set``, without editing ``step4_transient.toml`` or
creating a new file that outlives the experiment.

7. Where to go next
----------------------

.. code-block:: bash

   hmp viz list                                              # every registered figure name
   hmp viz show nancon_step5_export watershed_id_card         # re-render one figure on demand
   hmp catalog ls                                             # every run in this workspace
   hmp catalog show nancon_step5_export --detail              # metadata, metrics, Zarr layout

This page deliberately stops before calibration: the same Nançon project in
``examples/projects/04_streamflow_intermittence_in_transient/`` also carries
``run_calibration.toml``, which fits ``K`` and ``Sy`` instead of assuming
them, and ``run_calibration_by_hand.toml``, which runs the same two stages
with the method written out instead of named. See
:doc:`../user_guide/workflows/calibration` when step 4's assumed parameters
are not good enough, and
:doc:`../user_guide/workflows/stream-network-calibration` for the two-stage
method those two files run.

- :doc:`../user_guide/concepts/workspace-layout` for the resolution rules
  behind ``data/<variable>/`` and ``--workspace``.
- :doc:`../user_guide/results-and-exports` for what ``[export]`` can write
  besides GeoTIFF.
- :doc:`simulation-walkthrough` for a second end-to-end case, with Gmsh
  meshing instead of a structured grid.
