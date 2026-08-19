Python API
==========

HydroModPy exposes its top-level verbs through ``import hydromodpy as hmp``.
Each verb mirrors a CLI subcommand so ``hmp.run("cfg.toml")`` and
``hmp run cfg.toml`` execute the same workflow. The functions are
re-exported from :mod:`hydromodpy._api`.

Catalog and indexing
--------------------

- :func:`hydromodpy.open` -- the single door to a project catalog (object
  access, DataFrames, and schema discovery). Replaces the former
  ``open_catalog``.
- :func:`hydromodpy.index` -- open the machine-wide global index of projects.

Workflow launchers
------------------

- :func:`hydromodpy.run` -- run any workflow from a TOML file or config object;
  dispatches on ``[workflow] mode`` (simulation, overview, comparison, mesh,
  testbed).
- :func:`hydromodpy.calibrate` -- run a calibration workflow.

Analysis and reporting
----------------------

- :func:`hydromodpy.compare_pair` -- compare two simulations by id.
- :func:`hydromodpy.report` -- render the HTML calibration report.
- :func:`hydromodpy.read` -- read a variable from a simulation Run with
  auto-dispatch.

Diagnostics
-----------

- :func:`hydromodpy.doctor` -- lightweight environment diagnostic.

.. toctree::
   :maxdepth: 1
   :caption: Verbs

   open
   index_verb
   run
   calibrate
   compare_pair
   report
   read
   doctor
