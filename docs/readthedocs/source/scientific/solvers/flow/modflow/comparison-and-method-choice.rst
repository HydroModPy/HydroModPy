Comparison And Method Choice
============================

Use this page as the MODFLOW-family entry point when a result differs between
``flow/modflow6`` and ``flow/modflownwt``.

Before attributing a difference to the numerical backend, check the comparison
contract in this order:

- physical support and active cells;
- mesh topology and vertical representation;
- stress periods, forcing aggregation, and initial state convention;
- recharge, storage, drainage, imposed-head, and well package semantics;
- output variable role: state snapshot, period budget, or reduced diagnostic.

The detailed scientific comparison is documented in:

- :doc:`../../modflow6-vs-modflownwt-scientific-comparison`
- :doc:`../../solver-capability-matrix`
- :doc:`../../modflow-governing-equation-and-cvfd-formulation`
- :doc:`../../modflow-package-semantics-and-boundary-conditions`

For benchmark-style comparisons across solvers, also read the comparison
workflow output conventions:

- :doc:`../../../../getting_started/comparison-output-reading-order`
- :doc:`../../../../user_guide/results-and-exports`
