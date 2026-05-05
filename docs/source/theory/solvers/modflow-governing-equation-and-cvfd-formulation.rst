MODFLOW Governing Equation And CVFD Formulation
===============================================

Purpose
-------

This page is the scientific entry point for the MODFLOW-family flow backends in
HydroModPy.

Its role is narrower than a full MODFLOW manual and more explicit than a simple
backend overview:

- state the governing groundwater-flow problem that HydroModPy expects
  ``modflownwt`` and ``modflow6`` to solve,
- explain the control-volume finite-difference perspective used by the
  MODFLOW family,
- identify which parts of the formulation belong to official MODFLOW
  documentation and which parts belong to HydroModPy's own scientific
  contract and method choices,
- provide the chapter map for the deeper MODFLOW scientific notes that should
  grow around this page.

Primary Official Anchors
------------------------

The scientific material on this page should stay aligned with the following
primary sources:

- `USGS TM 6-A55, Documentation for the MODFLOW 6 Groundwater Flow Model <https://pubs.usgs.gov/publication/tm6A55>`_
  :
  governing equation, control-volume finite-difference formulation, storage,
  and stress-package concepts for MODFLOW 6.
- `USGS TM 6-A56, Documentation for the XT3D Option in the Node Property Flow Package of MODFLOW 6 <https://pubs.usgs.gov/publication/tm6A56>`_
  :
  extended conductance formulation and the reason XT3D matters on irregular
  grids.
- `MODFLOW 6 Input Guide <https://modflow6.readthedocs.io/en/latest/mf6io.html>`_
  :
  package-level definitions for ``DIS``, ``DISV``, ``NPF``, ``STO``, ``CHD``,
  ``DRN``, ``WEL``, ``RCHA``, ``EVT``, ``IMS``, and ``OC``.
- `Online Guide to MODFLOW-NWT <https://water.usgs.gov/ogw/modflow-nwt/MODFLOW-NWT-Guide/index.html>`_
  :
  the legacy Newton-based path still used by HydroModPy for the structured
  MODFLOW-NWT branch.

HydroModPy documentation should build from these sources rather than replacing
them.

Scope In HydroModPy
-------------------

This page is about the HydroModPy use of the MODFLOW groundwater-flow family:

- ``modflownwt`` as the legacy structured-grid flow backend,
- ``modflow6`` as the modern backend for both structured and runtime
  unstructured mesh paths,
- the common solver-agnostic ``[flow]`` scientific payload that HydroModPy
  maps to those two backends.

This page is not the place for:

- FloPy call signatures,
- package-by-package input syntax,
- transport details beyond their coupling boundary to flow,
- software class layout.

Those topics belong in the existing architecture notes or in dedicated package
pages.

HydroModPy-Level Governing Problem
----------------------------------

At the HydroModPy level, the canonical unknown is hydraulic head :math:`h`.

The shared groundwater problem is expressed in terms of:

- storage,
- internal groundwater flow between neighbouring control volumes,
- imposed-head or head-dependent boundary exchanges,
- diffuse areal forcing,
- localized sources and sinks.

One schematic PDE-style reading is:

.. math::

   S(h)\,\frac{\partial h}{\partial t}
   - \nabla \cdot \left(K \nabla h\right)
   = q_{\mathrm{in}} - q_{\mathrm{out}}

This is intentionally schematic. HydroModPy does not claim that every backend
uses the exact same continuous reduction or the exact same closure laws.

What HydroModPy does require is a stable scientific contract:

- head is the primary state variable,
- hydraulic properties are expressed before backend translation,
- storage, recharge, wells, imposed-head boundaries, and drainage semantics
  are normalized before assembly,
- backend differences are then made explicit rather than hidden.

Relation To The MODFLOW Family
------------------------------

The MODFLOW family solves groundwater flow through a control-volume
finite-difference perspective.

The key scientific ideas that HydroModPy should explain here are:

- one hydraulic-head unknown per cell,
- one water-balance equation per cell,
- intercell exchange written through conductance-like connections,
- storage and stress terms added to that cell balance,
- geometry carried by one discretization package such as ``DIS`` or ``DISV``.

.. figure:: /_static/theory/modflow/modflow_cell_balance.svg
   :alt: MODFLOW control-volume cell balance with internal flow and stress terms
   :width: 100%

   This is the minimal mental model used by the HydroModPy documentation: one
   head unknown per cell, intercell exchanges through conductance-like terms,
   and package stresses added to the same cell balance.

At the cell-balance level, a useful schematic reading is:

.. math::

   \sum_{j \in \mathcal{N}(i)} C_{ij}\,(h_j - h_i)
   + Q_i(h)
   = S_i\,\frac{\Delta h_i}{\Delta t}

where:

- :math:`i` is one control volume,
- :math:`\mathcal{N}(i)` is the set of connected neighbouring cells,
- :math:`C_{ij}` is the intercell conductance term,
- :math:`Q_i` collects stress-package contributions for that cell,
- :math:`S_i` represents the storage side of the transient balance.

This is not meant to replace the official derivations in TM 6-A55. It is the
minimum common mathematical picture HydroModPy needs in public documentation.

From Equation To Published Results
----------------------------------

The equation and the cell balance above should always be connected back to
actual model outputs. Two useful result anchors are:

.. figure:: /_static/capability_gallery/validation/dupuit_fixed_head_1d__modflow6.png
   :alt: MODFLOW 6 Dupuit fixed-head validation result
   :width: 100%

   A small validation result is the cleanest way to read the cell balance. The
   geometry, boundary heads, recharge, and analytical profile are controlled,
   so discrepancies are easier to interpret than on a real basin.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_piezometric_map.png
   :alt: Piezometric map from the Nancon transient MODFLOW-NWT run
   :width: 100%

   A real-basin result shows the other end of the same chain: after package
   assembly and execution, the primary state is still a hydraulic-head field
   that must be read together with the support, forcing, and boundary choices.

Scientific Questions HydroModPy Must Answer Explicitly
------------------------------------------------------

Using MODFLOW inside HydroModPy raises questions that the official USGS manuals
do not answer for the project automatically.

The documentation here should therefore make the following choices explicit:

1. How the solver-agnostic ``[flow]`` payload becomes MODFLOW-family cell
   terms.
2. Which public package subset HydroModPy actually uses today.
3. When ``DIS`` versus ``DISV`` is part of the scientific method choice.
4. How ``Sy`` and ``Ss`` are interpreted in the current vertical contract.
5. When HydroModPy treats a boundary as imposed head versus head-dependent
   exchange.
6. Why ``modflow6`` is preferred for irregular runtime meshes.
7. Why ``modflownwt`` is still kept for legacy structured comparisons and the
   ``MT3DMS`` / ``MODPATH`` ecosystem.
8. Why XT3D is treated as a first-class numerical-method choice rather than an
   invisible implementation detail.

Recommended Chapter Structure
-----------------------------

The MODFLOW scientific block should grow around the following structure.

1. Common governing equation and normalized HydroModPy scientific contract.
   This page should explain the unknown, the sign conventions, and the
   PDE-to-cell-balance reading.
2. Geometry and discretization path.
   Explain ``DIS`` versus ``DISV``, control-volume interpretation, and why mesh
   choice is already a scientific decision.
3. Internal flow law.
   Explain what ``NPF`` means scientifically, including conductivity,
   anisotropy, convertible cells, and the role of XT3D.
4. Storage and transient terms.
   Explain ``STO``, ``Sy``, ``Ss``, steady/transient flags, and the current
   vertical representation assumptions.
5. Boundary and forcing package semantics.
   Explain ``CHD``, ``DRN``, ``WEL``, ``RCHA``, ``EVT``, and the current
   project-level simplifications.
6. Nonlinearity and solver policy.
   Explain Newton behaviour, wetting/drying, IMS choices, and what stays
   specific to the legacy NWT branch.
7. Backend-selection rationale.
   Explain when ``modflow6`` is scientifically preferred and when
   ``modflownwt`` is still the right comparison or compatibility choice.
8. Evidence and comparison reporting.
   Explain what should be reported in validation and comparison pages so that
   solver choice, mesh choice, and XT3D choice are not silently mixed.

Immediate Writing Backlog
-------------------------

The next concrete additions should now be:

1. expand the internal-flow-law section with a careful TM 6-A55 reading of the
   ``NPF`` role;
2. add one explicit ``DIS`` versus ``DISV`` subsection with HydroModPy runtime
   examples;
3. add one short subsection on Newton behaviour and why the legacy NWT path
   still matters for some unconfined structured cases;
4. connect this page to one public scientific ``modflow6`` versus
   ``modflownwt`` comparison note;
5. connect comparison workflow pages back to the exact method choices they are
   exercising.

How This Page Relates To Existing Notes
---------------------------------------

This page should stay near the top of the MODFLOW scientific reading order.

Then readers should continue with:

- :doc:`modflow6-vs-modflownwt-scientific-comparison`
- :doc:`modflow-family-methods`
- :doc:`modflow-package-semantics-and-boundary-conditions`
- :doc:`vertical-representation-and-storage-assumptions`
- :doc:`xt3d-on-irregular-disv-meshes`
- :doc:`../../architecture/solver/modflow6-architecture-notes`
- :doc:`../../architecture/solver/modflownwt-architecture-notes`

Current Limitation
------------------

HydroModPy already documents many MODFLOW choices in fragments, but still lacks
one public note that fully walks from:

- the governing equation,
- to the MODFLOW control-volume formulation,
- to the package subset actually used by the project,
- to the scientific reason a user would choose one backend or mesh path over
  another.

This page is intended to become that anchor.
