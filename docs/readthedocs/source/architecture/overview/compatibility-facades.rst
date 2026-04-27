Compatibility Facades
=====================

Scope
-----

HydroModPy keeps a small number of compatibility layers so that public
import paths stay stable when internals are reorganized. This page lists
the ones that are still active in the current codebase.

Active facades
--------------

- ``hydromodpy/spatial/geographic/__init__.py``
  Re-exports the ``CatchmentDelineation`` runtime and the catchment
  helpers that now live in
  ``hydromodpy.spatial.geographic.core``. Existing scripts can keep
  importing from ``hydromodpy.spatial.geographic`` without knowing where
  each helper actually sits.
- ``hydromodpy/display/__init__.py``
  Stable public surface over the figure catalog. Implementations live
  under ``hydromodpy.display.figures``; users only see the catalog
  registration API and the public ``get`` and ``list_figures`` helpers.
- ``hydromodpy/solver/compatibility.py``
  Planner-facing capability matrix. It is not an import shim. It
  declares which earlier capabilities must exist before a process and
  solver pair can be planned.

Recommended reading order
-------------------------

1. ``hydromodpy/spatial/geographic/__init__.py``
2. ``hydromodpy/display/__init__.py``
3. ``hydromodpy/solver/compatibility.py``

Together they show the two patterns used in the repository:

- import-path compatibility for humans and downstream scripts,
- capability compatibility for planner orchestration.

Two patterns at work
--------------------

Stable public-package surfaces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A facade can be intentional. ``hydromodpy.display`` is the canonical
example: implementations move freely under ``hydromodpy.display.figures``
while the package keeps a stable ``get``, ``list_figures``, and
``register`` API. Users never need to know which internal module owns a
figure.

Planner compatibility registries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hydromodpy.solver.compatibility`` solves a different problem. It does
not republish names. It answers a binding question:

  Which earlier capabilities must exist before this process and solver
  pair can run?

The compatibility matrix is consumed by the simulation planner before
the run is scheduled.

Why facades exist at all
------------------------

Without explicit compatibility surfaces, every reorganization would
force noisy import churn across:

- user scripts,
- notebooks,
- generated examples,
- launcher code,
- transitional internal packages.

Facade modules localize that churn. Implementation packages can move
first, the public import surface can stay stable for one or more release
cycles, and the deprecation cleanup can happen later with clear
ownership.

Tradeoffs and risks
-------------------

Compatibility facades carry real maintenance cost. The main risks are:

- duplicated public entry points that confuse new contributors,
- lazy-import indirection that hides where code really lives,
- accidental growth of legacy surfaces that should be retired,
- circular-import pressure if a facade starts owning business logic.

Practical rules for the repository:

- keep compatibility modules thin,
- avoid putting new domain logic in them,
- document the canonical implementation package in the module docstring,
- prefer re-exporting or lazy loading over copy-pasting code,
- remove the facade once the compatibility window is no longer
  justified.

When to add or remove one
-------------------------

Add a compatibility facade when:

- a public import path is already used outside the package,
- a reorganization would otherwise create broad, noisy churn,
- the old and new surfaces map cleanly and mechanically.

Do not add one when:

- the API is still internal and unstable,
- the shim would need to maintain different semantics instead of one
  stable delegation path,
- the compatibility burden would outlive the migration benefit.

Remove or shrink one when:

- downstream callers have been migrated,
- the facade is the only remaining user of an old naming scheme,
- the indirection now makes the architecture harder to understand than
  the breaking change would have been.

Historical note
---------------

A previous ``hydromodpy.modeling`` import facade lived in the codebase
to redirect old MODFLOW and timeseries imports. It has been removed:
new code imports directly from ``hydromodpy.solver`` (engines,
adapters), ``hydromodpy.results`` (run-level access), or
``hydromodpy.physics.hydrology`` (PyHELP). The deprecation page at
:doc:`../../api/hydromodpy-watershed` documents the matching renames
for the older watershed facade.
