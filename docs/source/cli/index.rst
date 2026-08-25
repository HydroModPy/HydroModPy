CLI reference
=============

HydroModPy exposes two equivalent console entry points, :command:`hmp` and
:command:`hydromodpy`. The documentation uses :command:`hmp` for brevity.
This section is the authoritative command inventory.

.. code-block:: bash

   hmp --help              # top-level verbs
   hmp <family> --help     # sub-actions of one family
   hmp <family> <action> --help

Every leaf parser carries its own ``--help``, so the pages below focus on
intent rather than exhaustive flag tables.

Command inventory
-----------------

Eleven families group their own sub-actions; six verbs sit directly under
:command:`hmp`.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Family
     - Sub-actions
   * - :doc:`hmp workspace <workspace>`
     - ``init``, ``list``, ``register``, ``search``, ``forget``, ``prune``,
       ``clean``
   * - :doc:`hmp project <project>`
     - ``new``, ``list``, ``show``, ``delete``
   * - :doc:`hmp catalog <catalog>`
     - ``ls``, ``query``, ``show``, ``gc``, ``reindex``, ``delete``,
       ``restore``, ``trash``, ``tag``, ``note``, ``rename``, ``diff``,
       ``watch``, ``export``, ``import``, ``rerun``
   * - ``hmp data``
     - ``ls``, ``get``, ``check``, ``add``, ``remove``, ``prune``,
       ``archive``, ``restore``, ``export``, ``export-package``, ``import``
   * - :doc:`hmp viz <viz>`
     - ``list``, ``show``, ``gallery``
   * - ``hmp config``
     - ``template``, ``check``, ``schema``, ``wizard``
   * - :doc:`hmp dev <dev>`
     - ``run-script``, ``completion``, ``schema``, ``lock``, ``rank``,
       ``manage``
   * - :doc:`hmp audit <audit>`
     - ``list``, ``verify``, ``prune``
   * - :doc:`hmp privacy <privacy>`
     - ``purge``, ``verify``
   * - ``hmp site-selection``
     - ``plan``, ``select-catchments``, ``build-observed``,
       ``build-generated``, ``report``
   * - ``hmp report``
     - ``render``, ``compare``, ``catchment``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Flat verb
     - Role
   * - :doc:`hmp run <run>`
     - Run a workflow from a TOML config.
   * - :doc:`hmp calibrate <run>`
     - Run a calibration workflow from a TOML config.
   * - :doc:`hmp spinup <run>`
     - Cyclic spin-up: restart each cycle until heads and lake stage
       converge.
   * - ``hmp test``
     - Run unit, regression or validation test subsets.
   * - ``hmp doctor``
     - Diagnose the environment: Python, dependencies, solver binaries,
       workspace resolution, index-versus-disk consistency.
   * - ``hmp install-binaries``
     - Download MODFLOW, MODPATH and MT3D-USGS binaries into the managed
       cache.

Addressing a run
----------------

Every command that takes a run accepts the same reference grammar: the run
name (``cheze_baseline``), a versioned name (``cheze_baseline.v3``), a
unique id prefix (``9c41aa02``), the full id, or a selector. Selectors are
``@last``, ``@last~N``, ``@best:METRIC``, ``@worst:METRIC`` and
``@running``. A bare name resolves to the latest version of that stem.

Families
--------

.. toctree::
   :maxdepth: 1

   run
   project
   catalog
   workspace
   viz
   audit
   privacy
   dev

Operational reference
---------------------

.. toctree::
   :maxdepth: 1

   exit-codes
   completion

Related pages
-------------

- :doc:`/getting_started/cli-quickstart` for the first-run path.
- :doc:`/user_guide/results-and-exports` for reading and exporting results.
- :doc:`/user_guide/catchment-report` for the ``catchment_report.toml``
  contract behind ``hmp report catchment``.
