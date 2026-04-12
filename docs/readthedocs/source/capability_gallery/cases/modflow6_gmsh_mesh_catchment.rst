.. This file is compatible with ``python -m tools.doc_gallery`` outputs.

MODFLOW 6 on a Gmsh Catchment Mesh
==================================

.. note::
   The full run folder is intentionally not committed. This page uses selected
   figures published from ``examples/projects/launcher_simulation`` into
   ``examples/capability_gallery``.

This case keeps the standard ``process_simulation`` launcher while using
``mesh_catchment`` to build a triangular Gmsh mesh before the MODFLOW 6 solve.
The same run then executes MODFLOW 6 GWT transport on the generated flow model.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_flow_state_triptych.png
   :alt: Triptych showing topography, hydraulic head, and water-table depth on a Gmsh mesh
   :width: 100%

   Solver-agnostic flow-state synthesis: topography, hydraulic head, and
   water-table depth on the same triangular mesh.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_recharge_discharge_cumulative.png
   :alt: Cumulative recharge and discharge curves
   :width: 100%

   Cumulative recharge and discharge curves from the same launcher run.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_support_overview.png
   :alt: Runtime Gmsh support overview used by MODFLOW 6
   :width: 100%

   Runtime support diagnostic showing mesh supports, stream support, boundary
   labels, and resolved wells.

What It Shows
-------------

- How MODFLOW 6 consumes the same runtime Gmsh mesh contract used by other solvers.
- How the flow-state triptych relates topography, hydraulic head, and water-table depth.
- How cumulative recharge and discharge can be inspected without committing a full run folder.

Reproduce
---------

Run the underlying example with:

.. code-block:: bash

   python -m hydromodpy run examples/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml

Source Pointers
---------------

- ``examples/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml``
- ``examples/projects/launcher_simulation/config_mf6_mesh_catchment_common.toml``
- ``examples/capability_gallery/launcher_simulation/modflow6_gmsh_mesh_catchment/manifest.json``
- ``hydromodpy/analysis/display/figures/flow_synthesis.py``
- ``hydromodpy/analysis/capability_gallery.py``

Artifacts
---------

- ``docs/readthedocs/source/_static/capability_gallery/simulation/modflow6_gmsh_flow_state_triptych.png``
- ``docs/readthedocs/source/_static/capability_gallery/simulation/modflow6_gmsh_recharge_discharge_cumulative.png``
- ``docs/readthedocs/source/_static/capability_gallery/simulation/modflow6_gmsh_support_overview.png``
- ``docs/readthedocs/source/_static/capability_gallery/simulation/modflow6_gmsh_mesh_catchment_summary.json``
