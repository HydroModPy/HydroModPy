Solver Architecture
===================

This section documents software architecture for solver wrappers and backend
orchestration.

Use it when you want:

- the backend-specific code layout of ``boussinesq``, ``modflow6``, and
  ``modflownwt``,
- the split between generic simulation adapters and concrete solver packages,
- the current mesh contract supported by each flow backend.

Scientific derivations and mathematical solver notes live under
:doc:`../../theory/solvers/index`.

.. tab-set::

   .. tab-item:: Boussinesq

      In-house triangular-mesh backend with its own runtime and numerical
      formulations. See :doc:`boussinesq-uml-diagrams`.

   .. tab-item:: MODFLOW 6

      FloPy-backed flow and transport stack that shares the MODFLOW-family
      runtime lifecycle and can also consume runtime Gmsh meshes. See
      :doc:`modflow6-architecture-notes`.

   .. tab-item:: MODFLOW-NWT

      Legacy MODFLOW-family backend used with structured ``sgrid`` supports
      and the ``MT3DMS`` / ``MODPATH`` ecosystem. See
      :doc:`modflownwt-architecture-notes`.

   .. tab-item:: MODFLOW contracts

      The DIS, BAS, and package-stack contracts honoured by every
      MODFLOW-family backend, with the runtime invariants and the
      bridge to ``hydromodpy.spatial``. See :doc:`modflow-contracts`.

.. toctree::
   :maxdepth: 1

   boussinesq-uml-diagrams
   modflow6-architecture-notes
   modflownwt-architecture-notes
   modflow-contracts
