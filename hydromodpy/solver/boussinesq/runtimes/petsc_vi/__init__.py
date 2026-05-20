"""PETSc bounded VI runtime for the Boussinesq head-only obstacle formulation.

This package splits the experimental SNESVI runtime in three concerns:

- ``petsc``: pure PETSc utility helpers (SNES configuration, diagnostics).
- ``obstacle``: obstacle-specific math (clipping, reactions, projected residual).
- ``vi``: VI orchestration (substeps, diagnostics records, top-level solves).

The companion module ``petsc_vi_obstacle.py`` is the public facade.
"""

from __future__ import annotations
