hmp run, calibrate, spinup
==========================

Three flat verbs execute a workflow declared in a TOML file. They all write
their results into ``<project>/runs/<name>/``, next to the configuration.

hmp run
-------

Synopsis: ``hmp run [config] [--resume REF] [--from STEP] [--until STEP]
[--dry-run] [--frozen] [--force] [--no-lock] [--no-display] [--no-parallel]
[--overlay FILE] [--set PATH=VALUE] [--profile [HTML]]``

``hmp run`` reads the TOML, picks the workflow declared under
``[workflow].mode`` (``simulation``, ``overview``, ``calibration``,
``comparison``, ``testbed`` or ``site_selection``) and executes the whole
pipeline.

.. code-block:: bash

   hmp run projects/my_basin/run_demo.toml
   hmp run projects/my_basin/run_demo.toml --dry-run

Flags
~~~~~

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Flag
     - Effect
   * - ``--dry-run``
     - Print the resolved workflow, the sections found and the numbered
       pipeline steps. Nothing is executed.
   * - ``--resume REF``
     - Resume from the last journalled checkpoint. With a config, ``REF``
       is the run name or id to resume. Without a config, ``REF`` is a
       catalog reference and the run replays its own
       ``runs/<name>/config.toml``.
   * - ``--from STEP`` / ``--until STEP``
     - Start at, or stop after, a named or indexed pipeline step. Step
       names and indices come from ``--dry-run``.
   * - ``--force``
     - Run even when a completed run with an identical resolved config
       exists. Without it, the launch is skipped and points at the existing
       run. The forced result is versioned (``<name>.v2``).
   * - ``--frozen``
     - Reject any fresh download when ``hydromodpy.lock`` is present. Every
       artefact must already be in the cache and match its SHA-256.
   * - ``--no-lock``
     - Skip the post-run ``hydromodpy.lock`` write.
   * - ``--no-display``
     - Do not auto-render the figures listed in ``[display].figures``.
   * - ``--no-parallel``
     - Force sequential cohort execution. Useful for debugging,
       deterministic step ordering, single-CPU environments, or when
       parallel I/O contention shows up.
   * - ``--overlay FILE``
     - Merge an extra TOML payload after the ``base_config`` chain.
       Repeatable; later overlays win.
   * - ``--set PATH=VALUE``
     - Override one dotted TOML path after the overlays, for example
       ``--set workspace.project_root=/tmp/run``.
   * - ``--profile [HTML]``
     - Profile the execution with pyinstrument and write an interactive HTML
       report (default ``<config>.profile.html``). Also available on
       ``hmp calibrate`` and ``hmp spinup``, and from the TOML via
       ``[workflow] profile = true``; the CLI flag wins. Requires the
       ``profiling`` extra: ``pip install 'hydromodpy[profiling]'``.

Override precedence, lowest to highest: defaults, the ``base_config``
chain, ``--overlay`` files, then ``--set`` values. The environment
variables ``HMP_CACHE_HOME``, ``HMP_STATE_HOME``, ``HMP_BIN`` and
``HMP_WORKSPACE`` relocate machine caches and the shared data workspace;
they never patch a config field.

hmp calibrate
-------------

Synopsis: ``hmp calibrate <config> [--profile [HTML]]``

Shortcut for a TOML whose ``[workflow].mode`` is ``calibration``; the same
file also runs through ``hmp run``. The session journal is written live
under ``<project>/sessions/<stamp>-<method>-<id8>/`` as ``session.json``
plus ``trials.jsonl``, and the promoted runs land in ``runs/`` like any
other run.

Render the HTML report of a session with ``hmp report render <session or
run ref>``; it lands in ``share/reports/<session>/report.html``.

hmp spinup
----------

Synopsis: ``hmp spinup <config> [--then-run] [--profile [HTML]]``

Restarts the same simulation cycle after cycle, each cycle starting from
the converged state of the previous one, until heads and lake stage stop
moving. ``--then-run`` chains the full production chronicle from the
converged state once convergence is reached.
