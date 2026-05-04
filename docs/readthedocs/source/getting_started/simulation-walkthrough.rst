Simulation Walkthrough
======================

This is the recommended first end-to-end HydroModPy workflow. It keeps one
compact case, but still exercises geographic setup, embedded Gmsh meshing,
MODFLOW 6 flow, MODFLOW 6 transport, postprocessing, and curated gallery
publication.

.. important::

   Use this as the second step after :doc:`data-overview-walkthrough`, unless
   you already understand the geographic setup and only need a solver-oriented
   walkthrough.

What this workflow teaches
--------------------------

- Read one end-to-end case without starting from the full example inventory.
- See how a run overlay and a shared common config work together.
- Map the main forcing, support, and groundwater parameters to the published
  figures.
- Understand which outputs are useful for a first sanity check after the run.

Run it
------

.. code-block:: bash

   hmp run examples/projects/06_vire_selune/run_vire_mf6_irregular.toml

The matching static gallery page is
:doc:`../capability_gallery/cases/modflow6_gmsh_mesh_catchment`.

How the files relate
--------------------

- ``examples/projects/06_vire_selune/run_vire_mf6_irregular.toml``
  contains the run overlay: solver list, timeline, mesh-catchment
  refinement policy, and a few physics overrides.
- ``examples/projects/06_vire_selune/project_simulation.toml`` contains
  the shared geographic, domain, depth-model, data, and base flow
  setup. The run overlay inherits from it through ``base_config``.
- The ``[mesh_catchment]`` and ``[mesh_catchment.zone_meshing]`` blocks
  in the run overlay drive the Gmsh-backed irregular mesh. Switch to
  ``run_vire_mf6_regular.toml`` for a structured grid baseline on the
  same project.

Read the config in this order
-----------------------------

1. ``[simulation]`` and ``[[simulation.process]]``:
   confirm the workflow chain before looking at detailed parameters.
2. ``[simulation.time]``:
   understand the time support before interpreting any cumulative curve.
3. ``[data.recharge.sources]``:
   this is the first forcing block to read for this case.
4. ``[flow.param.*]``:
   start with ``K`` and ``Sy`` before touching more specialized options.
5. ``[mesh_catchment]`` and ``[mesh_catchment.zone_meshing]`` in the run
   overlay:
   these explain the support actually consumed by the solver.
6. ``[display]``:
   this tells you which synthesis figures should exist after the run.
7. ``[flow.bc.cauchy.drainage]`` and ``[flow.sinks_sources.recharge]``:
   these are the active boundary conditions and the recharge forcing
   wired into the run.

Map config sections to the displayed figures
--------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Figure
     - Read these sections first
     - What the figure helps you verify
   * - Support overview
     - ``[mesh_catchment]``, ``[geographic.river_network]``, well forcing blocks
     - Which mesh, stream support, and labels the runtime really used
   * - Flow-state triptych
     - ``[flow.ic]``, ``[flow.param.K]``, ``[flow.param.Sy]``, ``[modflow6.sgrid.vertical]``
     - How topography, head, and water-table depth react together on the same support
   * - Cumulative recharge/discharge
     - ``[simulation.time]``, ``[data.recharge.sources]``, ``[flow.sinks_sources.recharge]``, ``[flow.bc.cauchy.drainage]``
     - Whether the forcing chronology and discharge response are coherent over the selected time window

Parameters to look at first
---------------------------

- ``step_value``:
  change this first if you want to understand temporal aggregation.
- Recharge ``values`` and ``runoff_ratio``:
  these are the fastest way to make the cumulative curves move.
- ``K``:
  change this when you want to see how transmissive the system becomes.
- ``Sy``:
  change this when you want to see how strongly heads and depths react to the
  same forcing.
- ``global_size``, ``min_size``, and ``max_size``:
  change these when you want to see how the mesh support evolves.
- ``constraints_mode``:
  use this to understand which spatial structures are enforced during meshing.

First modifications to try
--------------------------

- Make the recharge series smoother or more contrasted.
- Lower or raise ``K`` by one order of magnitude.
- Change ``Sy`` to make storage response more or less damped.
- Tighten the mesh by lowering ``global_size``.
- Shorten or lengthen the simulation window without changing the geometry.

How to read the outputs
-----------------------

- Read the support overview first.
  If the support is wrong, the rest of the figures are already hard to trust.
- Read the triptych second.
  This is the most direct view of the simulated state on the chosen support.
- Read the cumulative curve last.
  It helps you interpret the run as a time-integrated response, not only as a
  spatial snapshot.
- When one figure surprises you, map it back to the controlling group:
  forcing, support, or groundwater parameters.

Where to go next
----------------

- Open
  :doc:`../capability_gallery/cases/example12_map_simulation_comparison` to compare
  two solver families on the same saved support.
- Use :doc:`reading-results-pages` to distinguish example pages,
  comparison pages, and analytical validation pages.
