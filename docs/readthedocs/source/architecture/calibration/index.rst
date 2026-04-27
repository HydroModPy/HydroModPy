Calibration Architecture
========================

This section documents the software architecture of the calibration stack.

It separates four complementary views:

- where the calibration entry point and orchestration live in the
  package,
- how one calibration session executes and records candidate runs,
- which core classes stay reusable across cases and methods,
- how runnable case packages are organized around the shared core.

.. tab-set::

   .. tab-item:: Overview

      Start with :doc:`calibration-overview` for the package map and the
      recommended code-reading path.

   .. tab-item:: Execution Flows

      Open :doc:`calibration-execution-flows` for activity and
      sequence views of one calibration session.

   .. tab-item:: Core Classes

      Open :doc:`calibration-core-classes` for the reusable config and runtime
      structures behind the calibration engine.

   .. tab-item:: Case Structure

      Open :doc:`calibration-case-structure` for the split between shared
      calibration core code and case-specific packages.

.. toctree::
   :maxdepth: 2

   calibration-overview
   calibration-execution-flows
   calibration-core-classes
   calibration-case-structure
