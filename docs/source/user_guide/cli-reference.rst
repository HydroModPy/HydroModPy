CLI reference
=============

The command-line reference lives in its own section: :doc:`/cli/index`.

It is the single authority for the ``hmp`` surface. Keeping the inventory
in one place is deliberate: two competing lists drift apart, and a stale
verb table is worse than no table.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Page
     - What it covers
   * - :doc:`/cli/index`
     - Every family, every sub-action, and the run-reference grammar.
   * - :doc:`/cli/run`
     - ``hmp run``, ``hmp calibrate``, ``hmp spinup`` and the workflow
       flags (``--dry-run``, ``--resume``, ``--overlay``, ``--set``, ...).
   * - :doc:`/cli/catalog`
     - Browsing, annotating, trashing, exporting and reindexing runs.
   * - :doc:`/cli/project` and :doc:`/cli/workspace`
     - Project and workspace lifecycle, plus the machine-wide index.
   * - :doc:`/cli/viz`
     - Figure discovery and rendering.
   * - :doc:`/cli/dev`
     - Developer-only verbs: schema, lockfile, prototype runner.
   * - :doc:`/cli/audit` and :doc:`/cli/privacy`
     - Audit log and certified purge.
   * - :doc:`/cli/exit-codes`
     - Typed exit codes for scripts and CI gates.
   * - :doc:`/cli/completion`
     - Shell completion for bash, zsh and fish.

For the first-run path, see :doc:`/getting_started/cli-quickstart`. For
reading and exporting results, see :doc:`results-and-exports`. For the
``catchment_report.toml`` contract behind ``hmp report catchment``, see
:doc:`catchment-report`.
