"""Strict experimental Picard/L-scheme initializer for steady Boussinesq.

This package splits the experimental initializer in four concerns:

- ``lscheme``: pure Picard/L-scheme iterate (bounded relaxed Newton-like solve).
- ``picard``: VI cycles (Picard blocks alternated with PETSc SNESVI checks) and
  the strict residual assembly used by both runtimes.
- ``diagnostics``: shared math/geometry helpers (bounds, free mask, quantiles).
- ``io``: JSON/CSV writers for diagnostics summaries.

The companion module ``stationary_picard_lscheme.py`` is the public facade.
"""

from __future__ import annotations
