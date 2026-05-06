Groundwater Flow Problem Definition
===================================

Purpose
-------

This page defines the common groundwater problem carried by the ``[flow]``
layer, before one backend translates it into MODFLOW-NWT, MODFLOW 6, or the
in-house Boussinesq solver.

The goal is not to pretend that all backends solve the exact same discrete
equations. The goal is to state the shared scientific contract:

- the primary unknown is hydraulic head,
- the problem is driven by storage, transmissive flow, boundary exchanges,
  recharge, and wells,
- and the runtime ``Flow`` object is the canonical place where those meanings
  are expressed before backend-specific assembly.

What The ``[flow]`` Layer Represents
------------------------------------

The ``Flow`` process is the canonical project-level description of a groundwater
simulation problem.

It groups:

- hydraulic properties,
- initial conditions,
- boundary conditions,
- sinks and sources,
- regime information such as steady or transient execution.

In code, the main runtime object is ``hydromodpy.physics.flow.flow.Flow``.
Scientifically, it should be read as the project-level statement:

``Given one aquifer geometry, one parameterization, one initial state, and one
set of forcings and exchanges, solve for groundwater head over space and
time.``

Generic Solver-Agnostic Statement
---------------------------------

At the most generic level, HydroModPy represents a head problem driven by:

- storage or accumulation,
- internal transmissive exchanges inside the aquifer,
- imposed-head boundaries,
- head-dependent exchanges such as drainage,
- diffuse areal forcing such as recharge or evapotranspiration,
- localized sources and sinks such as wells.

One convenient schematic balance is:

.. math::

   \mathcal{R}(h)
   =
   \mathcal{A}(h)
   + \mathcal{F}_{\mathrm{int}}(h)
   + \mathcal{F}_{\mathrm{bc}}(h)
   + \mathcal{Q}_{\mathrm{out}}(h)
   - \mathcal{Q}_{\mathrm{in}}
   = 0

where:

- :math:`\mathcal{A}` is the storage term in transient settings,
- :math:`\mathcal{F}_{\mathrm{int}}` is the internal groundwater-flow operator,
- :math:`\mathcal{F}_{\mathrm{bc}}` collects boundary exchanges driven by
  imposed heads or conductances,
- :math:`\mathcal{Q}_{\mathrm{out}}` collects sink terms,
- :math:`\mathcal{Q}_{\mathrm{in}}` collects source terms.

For readers who prefer PDE language, the same contract can be read
schematically as:

.. math::

   S(h)\,\frac{\partial h}{\partial t}
   - \nabla \cdot \left(T(h)\nabla h\right)
   =
   q_{\mathrm{recharge}}
   + q_{\mathrm{inj}}
   - q_{\mathrm{pump}}
   - q_{\mathrm{drain}}
   - q_{\mathrm{evt}}

This PDE-style reading is intentionally schematic. HydroModPy does not force
every backend into one identical continuous formulation:

- MODFLOW-family backends express the problem through ``NPF``, ``STO``,
  ``CHD``, ``DRN``, ``RCHA``, ``EVT``, and ``WEL`` packages,
- the Boussinesq backend makes thickness dependence and surface-interaction
  operators explicit in its finite-volume residual.

What This Looks Like In Results
-------------------------------

The shared problem definition is abstract, but the persisted outputs are not.
On a basin run, the first two result families to inspect are usually the state
field and the water budget.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_piezometric_map.png
   :alt: Piezometric map from the Nancon transient MODFLOW-NWT run
   :width: 100%

   The piezometric map is a direct view of the primary unknown: hydraulic head
   on the discretized basin support.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_water_budget.png
   :alt: Water budget from the Nancon transient MODFLOW-NWT run
   :width: 100%

   The water budget is the basin-scale reading of the source, sink, storage,
   and boundary-exchange terms listed in the schematic balance.

Canonical Unknown And Parameters
--------------------------------

Across the current repository, the main project-level unknown is hydraulic
head.

The most recurrent physical parameters are:

- hydraulic conductivity ``K``,
- specific yield ``Sy``,
- specific storage ``Ss``,
- geometry-related fields such as topography and substratum.

The runtime layer normalizes them into solver-independent scientific families.

.. list-table::
   :header-rows: 1
   :widths: 22 14 26 38

   * - Quantity
     - Typical units
     - Meaning at ``[flow]`` level
     - Typical backend interpretation
   * - Hydraulic head ``h``
     - ``m``
     - Primary state variable
     - ``IC`` / ``BAS`` initial heads, cell-centered unknown, diagnostics
   * - Hydraulic conductivity ``K``
     - ``m/s``
     - Lateral transmissive capacity
     - ``NPF`` conductivity arrays, transmissivity in Boussinesq
   * - Specific yield ``Sy``
     - ``-``
     - Unconfined storage
     - ``STO`` or effective storage term
   * - Specific storage ``Ss``
     - ``1/m``
     - Compressible storage
     - ``STO`` or effective storage term
   * - Topography / substratum
     - ``m``
     - Aquifer support and thickness envelope
     - Layer geometry, top and bottom elevations, wetted thickness

Initial Conditions
------------------

The current project-level initial-condition policy is simple by design. Head
can be initialized from:

- ``top``: start close to a full aquifer,
- ``bottom``: start close to an empty aquifer,
- ``custom``: start from one explicit scalar head.

Those policies are stored in normalized SI form before backend translation.
They are scientific choices about the starting state, not solver options.

Canonical Families Of Inputs
----------------------------

The ``[flow]`` block currently exposes a stable set of scientific input
families.

Initial conditions:

- head initialized from top,
- head initialized from bottom,
- custom scalar head.

Boundary conditions:

- lateral Dirichlet conditions on side boundaries,
- stream and ocean imposed-head style conditions,
- drainage-type head-dependent exchange.

Sinks and sources:

- diffuse recharge,
- wells,
- evapotranspiration-related terms where supported by the backend.

It is important to distinguish those families:

- imposed-head boundaries prescribe a head value and let the exchanged flux
  emerge from the solve,
- drainage is a head-dependent exchange law,
- recharge and evapotranspiration are areal forcings,
- wells are localized volumetric forcings.

Sign Conventions And Units
--------------------------

The repository already uses a mostly coherent set of physical conventions at
the ``Flow`` level.

.. list-table::
   :header-rows: 1
   :widths: 20 14 26 40

   * - Quantity
     - Units
     - Positive meaning
     - Current note
   * - Hydraulic head
     - ``m``
     - Higher piezometric level
     - Imposed-head boundaries store values in meters
   * - Recharge
     - ``m/s``
     - Water added to the aquifer
     - Normalized from data-manager conventions such as ``mm/day``
   * - Dedicated ETP
     - ``m/s``
     - Water removed from the aquifer
     - Diffuse sink, mainly used through ``EVT``-style assembly
   * - Well flux
     - ``m3/s``
     - Injection into the aquifer
     - Negative values mean pumping
   * - Drainage conductance
     - ``m2/s``
     - Stronger exchange capacity
     - Produces outflow only when the head exceeds the drainage level
   * - Imposed-head stage
     - ``m``
     - Not a signed flux
     - The sign of the resulting exchange depends on the solved head difference

One subtle but important distinction is this:

- the physical sign convention above is the one to use when discussing project
  inputs,
- each backend is still free to assemble its residual with its own internal
  algebraic sign convention.

For example, the Boussinesq residual uses positive residual contributions for
water leaving the cell, while keeping the physical interpretation above.

Boundary-Condition Families
---------------------------

HydroModPy currently exposes two main scientific boundary families.

Imposed-head family
^^^^^^^^^^^^^^^^^^^

The following identifiers carry imposed-head semantics in the common layer:

- ``west_side``
- ``east_side``
- ``north_side``
- ``south_side``
- ``stream``
- ``ocean``

At this level, the scientific meaning is only:

- one target support is selected,
- one stage or head value is prescribed on that support,
- the exchanged flux is not prescribed directly.

How that support is represented later depends on the backend:

- structured rows and columns,
- DISV support cells,
- or boundary edges in the Boussinesq mesh.

Head-dependent exchange family
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``drainage`` is the main current head-dependent exchange family. It should be
read as:

- a conductance-controlled release mechanism,
- activated only when the groundwater state reaches the drainage threshold,
- physically distinct from diffuse recharge,
- physically distinct from direct runoff observations.

This distinction matters for interpretation:

- recharge describes water entering the aquifer,
- drainage describes water leaving the aquifer because the piezometric state
  meets one release condition,
- runoff is not the same object and does not currently live in
  ``flow.sinks_sources``.

What Is Solver-Agnostic And What Is Backend-Specific
----------------------------------------------------

Solver-agnostic at ``[flow]`` level:

- head as the primary unknown,
- normalized units and sign conventions,
- semantic boundary identifiers such as ``ocean`` or ``drainage``,
- semantic forcing families such as recharge, ETP, and wells.

Backend-specific:

- exact spatial discretization,
- the detailed transmissive law,
- the exact package set or operator split,
- the representation of stream and ocean exchange,
- the surface-interaction closure used by the Boussinesq solver,
- optional numerical features such as XT3D or rewetting.

Current Backend Interpretations
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 18 41 41

   * - Backend family
     - What remains the same
     - What becomes backend-specific
   * - MODFLOW-NWT / MODFLOW 6
     - Head-based groundwater problem with recharge, wells, imposed heads,
       drainage, and storage
     - Package assembly, structured versus DISV support, XT3D, rewetting,
       detailed treatment of ``RCHA`` / ``EVT`` / ``DRN`` / ``CHD``
   * - Boussinesq
     - Head-based groundwater problem with the same physical families of
       forcing and exchange
     - Explicit finite-volume residual, thickness-dependent transmissivity,
       top drainage operator, and optional surface-interaction closure

Representative Validation Anchors
---------------------------------

The generic contract described on this page is not only conceptual. Several
gallery pages already exercise its main families of forcing and exchange.

- Side imposed heads plus steady recharge: :doc:`Dupuit Uniform Recharge 1D <../../capability_gallery/cases/dupuit_uniform_recharge_1d>`
- Divide plus downstream river-stage interpretation: :doc:`Dupuit Divide-River 1D <../../capability_gallery/cases/dupuit_divide_river_1d>`
- Transient recharge propagation: :doc:`Linearized Unconfined 1D Recharge Step <../../capability_gallery/cases/linearized_unconfined_recharge_step_1d>`
- Drainage as head-dependent release: :doc:`Linearized Unconfined Drainage 1D <../../capability_gallery/cases/linearized_unconfined_drainage_1d>`
- Ocean boundary in 2D: :doc:`Dupuit Circular-Island Ocean 2D <../../capability_gallery/cases/dupuit_circular_island_ocean_2d>`
- Thickness-dependent Boussinesq and ocean support behaviour: :doc:`Boussinesq Circular-Island Piecewise-K 2D <../../capability_gallery/cases/boussinesq_circular_island_piecewise_k_2d>`

Why This Page Matters
---------------------

Without this page, readers have to infer the scientific contract by combining:

- ``hydromodpy.physics.flow.flow.py``,
- backend adapter code,
- validation-case names,
- and scattered developer notes.

That is workable for maintainers, but it is too indirect for new contributors,
for scientific review, and for explaining why several numerical backends can
still belong to one modelling framework.

Current Source Anchors
----------------------

The most relevant anchors for the current version are:

- ``hydromodpy.physics.flow.flow``
- ``hydromodpy.physics.flow.flow_config``
- ``hydromodpy.physics.flow.boundary_conditions``
- ``hydromodpy.physics.flow.sinks_sources``
- ``hydromodpy.physics.flow.initial_conditions``
- :doc:`../hydrology/hydrological-forcing-chain`
- :doc:`../hydrology/recharge-and-surface-exchange-semantics`
- :doc:`../hydrology/stream-ocean-and-drainage-semantics`
- :doc:`../solvers/modflow-family-methods`
- :doc:`../boussinesq`
