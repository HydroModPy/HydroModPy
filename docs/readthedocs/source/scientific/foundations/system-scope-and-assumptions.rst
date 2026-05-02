System Scope And Assumptions
============================

Purpose
-------

This page is a first scaffold for the project-level scientific narrative that
is still largely missing from the published documentation.

Its long-term role should be to answer one question clearly:

"What kind of hydrological and hydrogeological system is HydroModPy designed to
model?"

Current Scientific Target
-------------------------

HydroModPy is currently oriented toward:

- catchment-scale shallow groundwater systems,
- mostly unconfined or weakly confined near-surface aquifers,
- domains where topography, hydrography, and geology strongly organize
  groundwater flow,
- workflows that combine spatial preprocessing, forcing preparation,
  groundwater simulation, validation, and comparison.

In practical terms, the repository is centered on the deployment and comparison
of groundwater-flow models on synthetic and geographic catchments rather than
on fully coupled land-surface or regional deep-basin modelling.

Main Scientific Chain
---------------------

At a high level, the intended scientific chain is:

.. code-block:: text

   climate or recharge information
   -> hydrological preprocessing or direct recharge forcing
   -> solver-agnostic groundwater problem
   -> concrete numerical backend
   -> postprocessed heads, fluxes, budgets, and diagnostics
   -> validation or calibration against references and observations

Shared Assumptions That Should Be Made Explicit
-----------------------------------------------

Several assumptions are already embedded in the code, but they are not yet
collected in one visible scientific page.

The shared assumptions currently include at least:

- a strong focus on shallow groundwater and catchment response,
- hydraulic properties driven by geology and spatial supports,
- geometry derived from topography, substratum, and optional runtime meshes,
- solver-dependent handling of groundwater/surface interaction,
- a distinction between project-level scientific payloads and backend-specific
  numerical representations.

Just as important, these assumptions are not identical across all backends.
Some are shared at the ``[flow]`` level, while others only become true once one
solver family is chosen.

What This Page Should Eventually Document
-----------------------------------------

This page should later be expanded into a compact but explicit project-level
reference covering:

1. Physical domain:
   catchment, aquifer thickness, role of topography, hydrography, and geology.
2. Water inputs and outputs:
   recharge, evapotranspiration, wells, stream and ocean interactions,
   drainage, saturation excess where applicable.
3. State variables:
   hydraulic head, saturated thickness, storage-related quantities, derived
   discharge metrics.
4. Scale assumptions:
   when HydroModPy is a good fit, and when it is not.
5. Backend envelope:
   what remains solver-agnostic versus what depends on MODFLOW-NWT,
   MODFLOW 6, or the in-house Boussinesq backend.

Current Source Anchors
----------------------

Useful code and documentation anchors for the future expansion are:

- :doc:`../../architecture/overview/mental-model-and-design-choices`
- :doc:`groundwater-flow-problem-definition`
- :doc:`../hydrology/hydrological-forcing-chain`
- :doc:`../solvers/index`
- ``hydromodpy/project.py``
- ``hydromodpy/physics/flow/flow.py``
- ``validation_cases/README.md``

Current Documentation Gap
-------------------------

Today, HydroModPy already documents software layers fairly well, but the
project-level scientific frame is still implicit and dispersed across:

- solver notes,
- validation-case descriptions,
- capability-gallery pages,
- developer design notes.

This page exists to turn that implicit knowledge into one canonical scientific
entry point.
