Worked MODFLOW Case: Linearized Unconfined Periodic Recharge 1D
===============================================================

This page keeps the scientific worked-case anchor for the 1D linearized
unconfined recharge example. The executable gallery case is:

- :doc:`/capability_gallery/cases/linearized_unconfined_recharge_periodic_1d`

Use it to check transient output conventions before interpreting a natural
basin run:

- the recharge signal has a clear chronology;
- the head response can be inspected as state snapshots;
- budgets must be read as values over stress-period intervals;
- timings can be compared independently from physical accuracy metrics.

The case is intentionally simpler than Nancon-like examples. Its role is to
separate temporal convention issues from mesh, topography, drainage, and
natural-basin configuration effects.

See also:

- :doc:`flow/modflow/common-concepts`
- :doc:`flow/modflow/comparison-and-method-choice`
- :doc:`/user_guide/concepts/comparison-output-reading-order`
