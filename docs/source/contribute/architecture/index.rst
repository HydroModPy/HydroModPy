Architecture
============

.. rst-class:: lead

How the code is organized: the layers and their allowed imports, the packages, the storage
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

      How an interrupted run restarts from the artifacts on disk.

Engine notes
------------

What a developer of an engine needs and cannot read at a glance in the code.

.. grid:: 1 2 3 3
   :gutter: 2 2 3 3

   .. grid-item-card:: Mesh engines
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/mesh-engines
      :link-type: doc

      The mesh engines behind one port and the cell mesh every solver reads.

   .. grid-item-card:: Mesh pivot
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/mesh-pivot
      :link-type: doc

      The HydroMesh pivot and who reads it.

   .. grid-item-card:: Solver backends
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/backends
      :link-type: doc

      MODFLOW 6, MODFLOW-NWT and Boussinesq, and the contracts of the MODFLOW family.

   .. grid-item-card:: Boussinesq engines
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/boussinesq-engines
      :link-type: doc

      The engines step by step, the experimental closures and the diagnostics of a run.

   .. grid-item-card:: From TOML to solver outputs
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/toml-to-solver
      :link-type: doc

      The path of a run with the objects named. The comparison of sealed runs follows.

   .. grid-item-card:: Calibration internals
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/calibration-internals
      :link-type: doc

      The loop of a session and its classes.

   .. grid-item-card:: Processes and boundaries
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/processes-and-boundaries
      :link-type: doc

      The runtime objects ``Flow`` and ``Transport``, and the flow boundary conditions.

   .. grid-item-card:: Stream network and spatial support
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: engines/stream-network-support
      :link-type: doc

      Supports, zones, hydrography, and the simulated active network.

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
   :caption: Engine notes

   engines/mesh-engines
   engines/mesh-pivot
   engines/backends
   engines/boussinesq-engines
   engines/toml-to-solver
   engines/calibration-internals
   engines/processes-and-boundaries
   engines/stream-network-support
