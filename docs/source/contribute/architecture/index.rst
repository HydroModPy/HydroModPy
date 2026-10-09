Architecture
============

.. rst-class:: lead

How the code is organised: the layers and their allowed imports, the packages, the storage
layout and the subsystems. For a task, start from the :doc:`recipes <how-to/index>`.

The foundations
---------------

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Mental model
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mental-model
      :link-type: doc

      How a TOML file becomes a stored run, why the boundaries are where they are, and the
      files to open first.

   .. grid-item-card:: Layered architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: layered-architecture
      :link-type: doc

      The import matrix, the rules the gate holds, and the rules a reviewer holds. The graph
      and the gate table are generated: :doc:`generated/layers`, :doc:`generated/guards`.

   .. grid-item-card:: Packages
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: packages/index
      :link-type: doc

      One page per top-level subpackage: its parts, its import rules, and where to add what.

   .. grid-item-card:: Storage layout
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: storage-layout
      :link-type: doc

      Disk is the truth and the database is an index: the data classes, naming, atomic
      writes, retention.

   .. grid-item-card:: Data scopes and schema evolution
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: data-scopes
      :link-type: doc

      The three databases, how their schemas move, and the canonical formats.

   .. grid-item-card:: Contracts and design patterns
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: contracts
      :link-type: doc

      The public facade, the storage Protocols, the field registry, and the patterns the code
      reuses.

   .. grid-item-card:: Pipeline resume
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: pipeline_resume
      :link-type: doc

      How an interrupted run restarts from the artefacts on disk.

Subsystems
----------

.. grid:: 1 2 3 3
   :gutter: 2 2 3 3

   .. grid-item-card:: Simulation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: simulation/toml-to-solver-walkthrough
      :link-type: doc

      From TOML to solver outputs. The comparison workflow and the testbed workflow follow.

   .. grid-item-card:: Solver backends
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: solver/backends
      :link-type: doc

      MODFLOW 6, MODFLOW-NWT and Boussinesq, and the contracts of the MODFLOW family. The
      Boussinesq diagrams follow.

   .. grid-item-card:: Mesh
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh/index
      :link-type: doc

      The catchment-conformal Gmsh pipeline, the structured grid, and the HydroMesh pivot.

   .. grid-item-card:: Calibration
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: calibration/index
      :link-type: doc

      The loop of a session and its classes, and the operational guide for adding methods.

   .. grid-item-card:: Data loading
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: data_loading/index
      :link-type: doc

      Planning and loading of input data, and the external provider constraints.

   .. grid-item-card:: Spatial support and field
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: spatial_support/index
      :link-type: doc

      Supports, zones, the field layer, hydrography, and the simulated active network.

   .. grid-item-card:: Processes
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: process/process-architecture
      :link-type: doc

      The runtime objects ``Flow`` and ``Transport``, and the flow boundary conditions.

.. toctree::
   :hidden:
   :maxdepth: 1

   mental-model
   layered-architecture
   generated/layers
   generated/guards
   packages/index
   storage-layout
   generated/storage-tree
   data-scopes
   contracts
   pipeline_resume

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Subsystems

   simulation/toml-to-solver-walkthrough
   simulation/comparison-workflow
   simulation/testbed-workflow-architecture
   solver/backends
   solver/boussinesq-engines
   solver/boussinesq-uml-diagrams
   mesh/index
   calibration/index
   data_loading/index
   spatial_support/index
   field/index
   process/process-architecture
   process/flow-boundary-conditions
