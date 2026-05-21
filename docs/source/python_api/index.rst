Python API
==========

HydroModPy exposes 13 top-level verbs through ``import hydromodpy as hmp``.
Each verb mirrors a CLI subcommand so ``hmp.run("cfg.toml")`` and
``hmp run cfg.toml`` execute the same workflow. The functions are
re-exported from :mod:`hydromodpy._api`.

Catalog and indexing
--------------------

- :func:`hydromodpy.open` -- open a workspace simulation catalog.
- :func:`hydromodpy.open_catalog` -- V1 catalog facade
  (simulations, inputs, projects).
- :func:`hydromodpy.index` -- open the machine-wide global index of workspaces.

Workflow launchers
------------------

- :func:`hydromodpy.run` -- run any workflow from a TOML file or config object.
- :func:`hydromodpy.calibrate` -- run a calibration workflow.
- :func:`hydromodpy.overview` -- run the overview workflow.
- :func:`hydromodpy.compare` -- run the comparison workflow.
- :func:`hydromodpy.testbed` -- run a TOML-driven method testbed.
- :func:`hydromodpy.mesh` -- run the standalone mesh launcher.

Analysis and reporting
----------------------

- :func:`hydromodpy.compare_pair` -- compare two simulations by id.
- :func:`hydromodpy.report` -- render the HTML calibration report.
- :func:`hydromodpy.read` -- read a variable from a simulation
  with auto-dispatch.

Diagnostics
-----------

- :func:`hydromodpy.doctor` -- lightweight environment diagnostic.

.. toctree::
   :maxdepth: 1
   :caption: Verbs

   open
   open_catalog
   index_verb
   run
   calibrate
   overview
   compare
   compare_pair
   testbed
   mesh
   report
   read
   doctor
