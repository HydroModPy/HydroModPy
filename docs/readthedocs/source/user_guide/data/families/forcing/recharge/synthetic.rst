Recharge Source: synthetic
==========================

Use ``source = "synthetic"`` for deterministic recharge series in tests,
tutorials, and analytical comparisons.

Minimal example
---------------

.. code-block:: toml

   [[data.recharge.sources]]
   source = "synthetic"
   values = [0.0, 2.0, 5.0, 2.0]
   start_date = "2000-01-01"
   freq = "D"
   source_unit = "mm/day"
   runoff_ratio = 0.0

Operational checks
------------------

- State whether ``values`` are absolute values or part of a waveform setup.
- Keep ``runoff_ratio`` explicit.
- Synthetic recharge is ideal for verifying solver assembly because the input
  chronology is known exactly.
