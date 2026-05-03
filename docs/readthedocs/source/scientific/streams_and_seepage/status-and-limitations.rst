Status And Limitations
======================

Purpose
-------

This page states what is currently supported, what is demonstrated by the
documentation examples, and what remains a future contract.

It should be read after :doc:`conceptual-model` and before using the examples
as validation evidence.

Current Supported Contract
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 26 38 36

   * - Topic
     - Current status
     - Evidence to inspect
   * - Conceptual separation
     - ``stream`` boundary, seepage/drainage operator, and
       ``simulated_active`` diagnostic are documented as distinct roles.
     - :doc:`conceptual-model`
   * - Didactic figures
     - Concept sketches are generated as SVG from
       ``render_method_sketches.py``. The stream is drawn as a zero-thickness
       surface support; seepage is controlled by ``h - z_s``.
     - ``/_static/concepts/streams_and_seepage/*.svg``
   * - MODFLOW 6 local drainage output
     - Raw DRN budget records are normalized into positive
       ``outflow_drain`` when the budget is available.
     - :doc:`../hydrology/simulated-active-network`
   * - MODFLOW 6 routed diagnostic
     - ``outflow_drain`` can be routed into ``accumulation_flux`` using
       structured routing, mesh-graph downhill routing, or a conservative local
       fallback.
     - :doc:`../hydrology/simulated-active-network`
   * - Active-network figures
     - Runs with ``accumulation_flux`` and plottable topology can expose
       ``simulated_active_network`` and
       ``simulated_active_network_reference_overlay`` figures.
     - :doc:`worked-examples`
   * - Comparison exports
     - Comparison workflows can export active-network occupancy metrics and
       overlap metrics against the observed ``reference`` network when the
       required fields and vector role are present.
     - :doc:`../../getting_started/comparison-output-reading-order`
   * - MODFLOW-NWT baseline
     - A stable Nancon MODFLOW-NWT basin page exists and is the best legacy
       baseline for reading order and figure interpretation.
     - :doc:`/capability_gallery/cases/nancon_transient_nwt`

What Is Demonstrated By The Examples
------------------------------------

The examples demonstrate an interpretation chain, not a universal calibration.

MODFLOW 6 active-network example
   Demonstrates that the result contract can be read as:

   .. code-block:: text

      head -> outflow_drain -> accumulation_flux -> simulated_active_network

Nancon wide-K sweep
   Demonstrates that active-network extent and overlap metrics react to
   hydraulic conductivity on one real-basin setup. It is useful for scientific
   reading and visual development. It is not a calibrated parameter estimate.

MODFLOW-NWT Nancon baseline
   Demonstrates a legacy structured-grid reading path: hydrographic network
   roles, active-network overlay, piezometric map, hydrograph, and water
   budget.

Comparison output reading order
   Demonstrates how to inspect audit, report, configuration, metrics, figures,
   and skipped-export diagnostics before making scientific claims.

Current Non-Contracts
---------------------

The following items are intentionally not claimed as stable contracts yet.

``hydrographic_network_simulated_active`` vector feature
   HydroModPy exposes computed active-network masks, metrics, and figures.
   It does not yet automatically persist a canonical vector feature named
   ``hydrographic_network_simulated_active``.

Default vectorization threshold
   Thresholds and time-window rules must remain explicit. A default canonical
   active-network vector would require a project-level choice of threshold,
   simplification, temporal mode, and persistence rule.

Full surface-water routing
   The current stream/seepage sketches do not represent channel storage, water
   depth, backwater effects, or routed river hydraulics. A river is drawn as a
   support for exchange, not as a finite-thickness water body.

Calibration-grade stream-network metric
   Current active-network overlap metrics are cell-overlap diagnostics. They
   are useful, but they are not yet the full bidirectional downslope-distance
   metric used by Abhervé et al. (2023).

K-only Nancon calibration protocol
   The committed Nancon sweep is a development and reading case. A clean
   calibration protocol should freeze the support across variants, declare the
   objective metric, and rerun the parameter search under that protocol.

Recommended Acceptance Checks
-----------------------------

Before saying that a new example or backend path is complete, verify:

- the method role is named: stream boundary, seepage/drainage operator, or
  simulated-active diagnostic;
- the support role is named: ``reference``, ``generated``, solver support, or
  routed post-processing graph;
- ``outflow_drain`` is treated as local positive groundwater outflow;
- ``accumulation_flux`` is treated as a routed diagnostic, not a mass-budget
  total;
- validation against observed hydrography uses ``reference`` and does not
  silently fall back to ``generated``;
- missing prerequisites produce ``*_skipped.json`` diagnostics or explicit
  absence of display capability;
- documentation examples point to concrete commands, output files, and figures.

Related Reading
---------------

- :doc:`conceptual-model`
- :doc:`worked-examples`
- :doc:`nancon-k-sweep-results`
- :doc:`../hydrology/simulated-active-network`
- :doc:`../../architecture/overview/hydrographic-network-simulated-active-inventory`
