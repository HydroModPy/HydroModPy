MODFLOW Governing Equation And CVFD Formulation
===============================================

Purpose
-------

This page is the scientific entry point for the MODFLOW-family flow backends in
HydroModPy.

Its role is narrower than a full MODFLOW manual and more explicit than a simple
backend overview:

- state the governing groundwater-flow problem that HydroModPy expects
  ``modflow_nwt`` and ``modflow6`` to solve,
- explain the control-volume finite-difference perspective used by the
  MODFLOW family,
- identify which parts of the formulation belong to official MODFLOW
  documentation and which parts belong to HydroModPy's own scientific
  contract and method choices,
- point to the deeper MODFLOW scientific notes.

Primary Official Anchors
------------------------

The material on this page follows these primary sources:

- USGS TM 6-A55, :cite:`langevin2017`,
  `Documentation for the MODFLOW 6 Groundwater Flow Model <https://pubs.usgs.gov/publication/tm6A55>`_:
  governing equation, control-volume finite-difference formulation, storage,
  and stress-package concepts for MODFLOW 6.
- `USGS TM 6-A56, Documentation for the XT3D Option in the Node Property Flow Package of MODFLOW 6 <https://pubs.usgs.gov/publication/tm6A56>`_:
  extended conductance formulation and the reason XT3D matters on irregular
  grids.
- `MODFLOW 6 Input Guide <https://modflow6.readthedocs.io/en/latest/mf6io.html>`_:
  package-level definitions for ``DIS``, ``DISV``, ``NPF``, ``STO``, ``CHD``,
  ``DRN``, ``WEL``, ``RCHA``, ``EVT``, ``IMS``, and ``OC``.
- USGS TM 6-A37, :cite:`niswonger2011`,
  `Online Guide to MODFLOW-NWT <https://water.usgs.gov/ogw/modflow-nwt/MODFLOW-NWT-Guide/index.html>`_:
  the legacy Newton-based path still used by HydroModPy for the structured
  MODFLOW-NWT branch, on top of the original MODFLOW-2005 ground-water flow
  process :cite:`harbaugh2005`.

This page builds on these sources and does not replace them.

Scope In HydroModPy
-------------------

This page is about the HydroModPy use of the MODFLOW groundwater-flow family:

- ``modflow_nwt`` as the legacy structured-grid flow backend,
- ``modflow6`` as the modern backend for both structured and runtime
  unstructured mesh paths,
- the common solver-agnostic ``[flow]`` payload that HydroModPy maps to those
  two backends.

This page is not the place for:

- FloPy call signatures,
- package-by-package input syntax,
- transport details beyond their coupling boundary to flow,
- software class layout.

Those topics belong in the architecture notes or in dedicated package pages.

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

The key ideas are:

- one hydraulic-head unknown per cell,
- one water-balance equation per cell,
- intercell exchange written through conductance-like connections,
- storage and stress terms added to that cell balance,
- geometry carried by one discretization package (``DISV`` in ``modflow6``, ``DIS`` in ``modflow_nwt``).

.. figure:: /_static/theory/modflow/modflow_cell_balance.svg
   :alt: MODFLOW control-volume cell balance with internal flow and stress terms
   :width: 100%

   This is the minimal model used in this documentation: one
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

This does not replace the official derivations in TM 6-A55. It is the minimum
common picture.

What HydroModPy Chooses
-----------------------

The USGS manuals describe the MODFLOW family. They do not say which parts
HydroModPy uses. This section lists the choices the code makes. The linked pages
give the detail.

Discretization package
   ``modflow6`` always builds a ``DISV`` grid, for structured and unstructured
   meshes alike, so that one code path serves both. ``modflow_nwt`` builds a
   ``DIS`` grid and refuses a mesh that is not structured. The mesh is therefore
   already a method choice. See :doc:`../mesh`.

Internal flow law
   Every layer is convertible (``icelltype`` is 1 in ``NPF``, ``iconvert`` is 1
   in ``STO``, ``laytyp`` is 1 in ``UPW``). XT3D is a ``modflow6`` option. When
   you do not set it, HydroModPy turns it off on a structured grid, and turns it
   on when horizontal anisotropy is present or when the mesh is strongly
   non-orthogonal. See :doc:`xt3d-on-irregular-disv-meshes`.

Storage
   ``Sy`` and ``Ss`` feed ``STO`` in ``modflow6`` and ``UPW`` in ``modflow_nwt``.
   Steady and transient stress periods are declared per period. See
   :doc:`vertical-representation-and-storage-assumptions`.

Boundaries and forcing
   Imposed-head boundaries become ``CHD``, drainage becomes ``DRN``, wells become
   ``WEL`` and recharge becomes ``RCHA`` in ``modflow6`` and ``RCH`` in
   ``modflow_nwt``. Evapotranspiration uses ``EVTA`` or ``EVT`` in ``modflow6``
   and ``EVT`` in ``modflow_nwt``. ``modflow6`` also builds ``SFR`` and ``LAK``
   packages. See :doc:`../exits`.

Nonlinearity
   ``modflow6`` uses the Newton formulation with under-relaxation by default, and
   an ``IMS`` solver. ``modflow_nwt`` uses the ``NWT`` solver. See
   :doc:`../mf6-vs-nwt`.

Particle tracking and transport
   The ``modflow_nwt`` branch carries ``MODPATH`` and ``MT3DMS``. The ``modflow6``
   branch has its own particle tracking (``PRT``) and transport code.

Where To Read Next
------------------

- :doc:`../groundwater-flow`
- :doc:`../solvers`
- :doc:`../mf6-vs-nwt`
- :doc:`../exits`
- :doc:`../mesh`
- :doc:`vertical-representation-and-storage-assumptions`
- :doc:`xt3d-on-irregular-disv-meshes`
- :doc:`/contribute/architecture/solver/modflow6-architecture-notes`
- :doc:`/contribute/architecture/solver/modflownwt-architecture-notes`
