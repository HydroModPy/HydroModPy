API Reference
=============

This hosted build publishes the stable facade and the user-facing guides.
The full recursive API tree is skipped on Read the Docs to keep the main
branch build inside the hosted time limit. Build the docs locally to render
every generated ``api/generated/`` page.

Public facade
-------------

The single supported import path is ``import hydromodpy as hmp``.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Symbol
     - Purpose
   * - ``hmp.open``
     - Open a project facade.
   * - ``hmp.open_catalog``
     - Open a simulation catalog.
   * - ``hmp.read``
     - Read configured project data.
   * - ``hmp.run``
     - Run a configured workflow.
   * - ``hmp.calibrate``
     - Run a calibration workflow.
   * - ``hmp.index``
     - Inspect registered workspaces.
   * - ``hmp.overview``
     - Build data overview outputs.
   * - ``hmp.compare_pair``
     - Compare two simulation outputs.
   * - ``hmp.mesh``
     - Build mesh artifacts.
   * - ``hmp.testbed``
     - Run a testbed workflow.
   * - ``hmp.report``
     - Build report outputs.
   * - ``hmp.bootstrap_proj``
     - Bootstrap a project file.
   * - ``hmp.doctor``
     - Inspect runtime health.

Public packages
---------------

Stable user-facing packages are ``hydromodpy.config``,
``hydromodpy.results``, ``hydromodpy.display``, ``hydromodpy.calibration``,
``hydromodpy.catalog``, and ``hydromodpy.project``. Contributor packages
follow the layered architecture documented in :doc:`/architecture/index`.

Docstring policy
----------------

.. toctree::
   :maxdepth: 1

   docstring-policy
