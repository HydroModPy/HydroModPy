Stream, Ocean, And Drainage Semantics
=====================================

Purpose
-------

This page documents three boundary or exchange families that are easy to
confuse because they all live near the land surface:

- ``stream``,
- ``ocean``,
- ``drainage``.

They do not play the same scientific role.

- ``stream`` and ``ocean`` currently act as stage or imposed-head style
  boundaries in the public modelling path,
- ``drainage`` acts as a head-dependent release operator,
- none of them should be confused with diffuse recharge,
- and none of them should be confused with runoff observations.

Conceptual Diagram
------------------

.. uml:: diagrams/surface_exchange_semantics_context.wsd

Why This Distinction Matters
----------------------------

Without one dedicated page, it is too easy to read all surface-related objects
as if they were just different names for water leaving or entering the model.

That is not the intended meaning.

.. list-table::
   :header-rows: 1
   :widths: 16 22 24 38

   * - Family
     - Prescribed quantity
     - Scientific meaning
     - What the solve returns
   * - ``stream``
     - stage or head ``m``
     - Exchange with one river-network support
     - resulting groundwater-to-stream or stream-to-groundwater flux
   * - ``ocean``
     - sea level ``m``
     - Exchange with one coastal support
     - resulting coastal inflow or outflow
   * - ``drainage``
     - conductance ``m2/s`` plus threshold geometry
     - Unilateral head-dependent release
     - resulting drainage outflow

Stream Semantics
----------------

At the current ``Flow`` level, ``stream`` should be understood as:

- one selected stream support on the mesh or grid,
- one prescribed stage or head value,
- one exchange flux that is not prescribed directly but emerges from the
  solved head field.

In other words, ``stream`` is currently closer to:

- a river stage boundary,
- or a prescribed surface-water head support,

than to a full surface-routing or river-hydraulics model.

Current public implementation notes:

- in MODFLOW-family paths, ``stream`` is currently assembled through
  ``CHD``-style constant-head supports rather than a full ``RIV`` law;
- in the Boussinesq path, ``stream`` is resolved to river-tagged cells or
  edges, then applied as a Dirichlet support.

This is a strong modelling simplification. It is acceptable in controlled
setups and in some basin-scale approximations, but it is not equivalent to a
riverbed-resistance model with explicitly parameterized conductance.

Ocean Semantics
---------------

``ocean`` is also a stage-controlled boundary family, but its support logic is
different from ``stream``.

Scientifically, ``ocean`` means:

- the sea level is prescribed,
- the coastal support is the part of the domain considered hydraulically
  connected to the sea,
- the exchanged flux is an output of the solve.

Current public implementation notes:

- the oceanic data path can inject a mean sea level or a mean time-series value
  into the active ``ocean`` boundary;
- in MODFLOW 6, the current public path translates this to ``CHD`` on cells
  whose support is considered ocean-influenced;
- in the current Boussinesq slice, coastal support is stage-dependent: cells or
  edges are selected where topography lies below the current sea threshold.

This means the public ocean path is currently:

- stage-controlled,
- geometry-aware,
- but not yet a conductance-limited ``GHB``-style coastal exchange law.

Drainage Semantics
------------------

``drainage`` is fundamentally different from ``stream`` and ``ocean``.

It does not prescribe a water level. It prescribes an exchange capacity and
lets outflow activate only when groundwater reaches the drainage condition.

Scientifically, ``drainage`` means:

- one head-dependent release mechanism,
- usually interpreted as seepage or drainage toward a surface interface or
  network,
- distinct from diffuse recharge,
- distinct from observed runoff,
- distinct from the current Boussinesq saturation-excess closure.

Current public implementation notes:

- in MODFLOW-family paths, ``drainage`` is assembled through ``DRN``-style
  head-dependent outflow;
- in the current Boussinesq slice, it is implemented as a top-drainage
  operator driven by conductance and activation above the top elevation.

What They Are Not
-----------------

``stream`` is not currently:

- a full river-routing model,
- a full riverbed conductance model in the public MODFLOW 6 path,
- a runoff observation.

``ocean`` is not currently:

- a tidal hydrodynamics model,
- a full conductance-limited coastal interface in the public path,
- a recharge term.

``drainage`` is not currently:

- direct runoff,
- a climatic forcing,
- identical to stream exchange,
- identical to the saturation-excess operator in the Boussinesq backend.

Current Public Path Diagram
---------------------------

.. uml:: diagrams/surface_exchange_runtime_path.wsd

Backend Reading Guide
---------------------

.. list-table::
   :header-rows: 1
   :widths: 18 41 41

   * - Backend family
     - ``stream`` and ``ocean``
     - ``drainage``
   * - MODFLOW-NWT / MODFLOW 6
     - Stage/head supports currently expressed through ``CHD``-style assembly
     - Head-dependent outflow currently expressed through ``DRN``
   * - Boussinesq
     - Dirichlet supports on resolved cells or edges
     - Top outflow operator driven by conductance and head exceedance

Validation And Comparison Anchors
---------------------------------

Useful pages already exist to validate or inspect these semantics in context.

- Stream-style imposed downstream stage: :doc:`Dupuit Divide-River 1D <../../capability_gallery/cases/dupuit_divide_river_1d>`
- Ocean boundary on a radial island benchmark: :doc:`Dupuit Circular-Island Ocean 2D <../../capability_gallery/cases/dupuit_circular_island_ocean_2d>`
- Ocean boundary with heterogeneous conductivity and Boussinesq comparison: :doc:`Boussinesq Circular-Island Piecewise-K 2D <../../capability_gallery/cases/boussinesq_circular_island_piecewise_k_2d>`
- Drainage boundary in a closed-form linearized setting: :doc:`Linearized Unconfined Drainage 1D <../../capability_gallery/cases/linearized_unconfined_drainage_1d>`
- Drainage boundary on sloping topography: :doc:`Linearized Unconfined Hillslope Drainage 1D <../../capability_gallery/cases/linearized_unconfined_hillslope_drainage_1d>`
- Cross-code behaviour with recharge and emergent drainage: :doc:`Surface-Interaction Ramp Code Comparison <../../capability_gallery/cases/surface_interaction_ramp_code_comparison>`
- MODFLOW package reading of the distributed drainage benchmark: :doc:`../solvers/worked-modflow-case-linearized-unconfined-drainage-1d`

Current Source Anchors
----------------------

- ``hydromodpy.physics.flow.boundary_conditions``
- ``hydromodpy.physics.flow.structure_binders``
- ``hydromodpy.solver.modflow6.modflow6``
- ``hydromodpy.solver.boussinesq.forcing.dirichlet_support_resolution``
- ``hydromodpy.solver.boussinesq.forcing.drainage_resolution``
- :doc:`recharge-and-surface-exchange-semantics`
- :doc:`../solvers/modflow-package-semantics-and-boundary-conditions`
- :doc:`../solvers/boussinesq-mathematical-notes`
