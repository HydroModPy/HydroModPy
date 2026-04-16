Compatibility Facades
=====================

HydroModPy keeps a small number of compatibility layers so public import paths
do not break every time internals are reorganized.

These facades are not meant to become permanent abstraction layers. Their job
is narrower:

- preserve stable import paths while packages are decomposed,
- keep launcher-facing APIs readable,
- centralize migration pressure instead of spreading legacy imports across the
  whole codebase.

Main Facade Families
--------------------

Historical import facades
~~~~~~~~~~~~~~~~~~~~~~~~~

Some modules exist primarily to preserve long-lived import paths:

- ``hydromodpy.modeling`` redirects historical imports such as ``modflow`` or
  ``timeseries`` toward their current packages through lazy imports,
- ``hydromodpy.spatial.geographic`` republishes the old geographic runtime
  facade while progressively exposing symbols that now live in
  ``hydromodpy.spatial.geographic.core``.

These facades are useful when external scripts or notebooks still import older
paths, but new code should prefer the canonical implementation package.

Stable public-package facades
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some compatibility modules exist because the public API wants one stable entry
point even though the implementation moved:

- ``hydromodpy.analysis.display.orchestration`` now republishes plotting suites
  that live in ``hydromodpy.analysis.display.suites``.

In this pattern, the compatibility surface is part of the intended package API,
not only a temporary migration shim.

Planner compatibility registries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Compatibility is not always an import problem. The simulation planner also
uses explicit compatibility declarations to answer:

"Which earlier capabilities must exist before this process/solver pair can run?"

That logic currently lives in ``hydromodpy.solver.compatibility`` and acts as a
static capability matrix for planner binding.

Why Facades Exist At All
------------------------

Without explicit compatibility modules, every reorganization would force
wide-ranging import churn across:

- user scripts,
- notebooks,
- generated examples,
- launcher code,
- transitional internal packages.

Facade modules keep that churn localized. They also make refactors safer:

- implementation packages can move first,
- the public import surface can remain stable for one or more release cycles,
- deprecation cleanup can happen later with clear ownership.

Tradeoffs And Risks
-------------------

Compatibility facades are useful, but they add real maintenance cost.

Main risks are:

- duplicated public entry points that confuse new contributors,
- lazy-import indirection that hides where code really lives,
- accidental growth of legacy surfaces that should instead be retired,
- circular-import pressure if facades start owning business logic.

Practical rules for the repository are therefore:

- keep compatibility modules thin,
- avoid putting new domain logic in them,
- document the canonical implementation package in the module docstring,
- prefer re-exporting or lazy loading over copy-pasting code,
- remove the facade when the compatibility window is no longer justified.

When To Add Or Remove One
-------------------------

Add a compatibility facade when:

- a public import path is already used outside the package,
- a reorganization would otherwise create broad, noisy churn,
- the old and new surfaces can be mapped clearly and mechanically.

Do not add one when:

- the API is still internal and unstable,
- the shim would need to maintain different semantics instead of one stable
  delegation path,
- the compatibility burden would outlive the migration benefit.

Remove or shrink one when:

- downstream callers have been migrated,
- the facade has become the only remaining user of an old naming scheme,
- the indirection now makes the architecture harder to understand than the
  breaking change would have been.

Reading The Code
----------------

Today, the clearest compatibility entry points to inspect are:

- ``hydromodpy/modeling/__init__.py``,
- ``hydromodpy/spatial/geographic/__init__.py``,
- ``hydromodpy/analysis/display/orchestration.py``,
- ``hydromodpy/solver/compatibility.py``.

Together they show the two main patterns used in HydroModPy:

- import-path compatibility for humans and downstream scripts,
- capability compatibility for planner orchestration.
