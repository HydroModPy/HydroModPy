Worked MODFLOW Cases
====================

This page groups executable MODFLOW-family examples that are useful when
checking solver behavior, output conventions, and comparison results.

Current stable worked case:

- :doc:`../../worked-modflow-case-nancon-transient-nwt-etp-evt`

Useful gallery and workflow pages:

- :doc:`../../../../capability_gallery/cases/nancon_transient_nwt`
- :doc:`../../../../capability_gallery/code_comparison`
- :doc:`../../../../user_guide/concepts/comparison-workflow`
- :doc:`../../../../user_guide/concepts/comparison-output-reading-order`

When adding a new worked case, keep the same reading order:

- configuration and physical support;
- mesh and active-domain diagnostics;
- forcing chronology and initial state;
- head or state snapshots;
- period budgets and cumulative budgets;
- comparison metrics and execution timings.
