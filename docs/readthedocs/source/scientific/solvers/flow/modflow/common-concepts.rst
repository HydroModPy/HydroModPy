Shared MODFLOW Concepts
=======================

This page is the stable entry point for concepts shared by the MODFLOW-family
flow solvers exposed by HydroModPy.

The detailed scientific material remains in the cross-cutting solver pages:

- :doc:`../../modflow-governing-equation-and-cvfd-formulation`
- :doc:`../../modflow-package-semantics-and-boundary-conditions`
- :doc:`../../modflow-family-methods`

The common contract is intentionally limited to concepts that must be checked
before comparing MODFLOW 6 and MODFLOW-NWT outputs:

- the same physical support and active-domain convention;
- the same forcing chronology and stress-period interpretation;
- equivalent recharge, storage, drainage, imposed-head, and well semantics;
- explicit documentation of backend-specific limitations;
- comparison of state outputs, budget outputs, and timings with their own
  temporal conventions.

This separation keeps version-specific pages focused on backend assembly while
leaving shared assumptions in one place.
