"""Strict experimental Picard/L-scheme initializer for steady Boussinesq.

This module is intentionally isolated from the default runtime selection path.
It is an investigation helper for difficult steady obstacle cases. The method
keeps the original head-only problem definition: no artificial minimum
saturated thickness is introduced and no drainage/surface conductance is added.

The Picard iterate solves a lagged linear transmissivity problem, adds a purely
algorithmic L-scheme diagonal damping term, relaxes the update, projects the
head into the physical bounds, and evaluates the strict bounded residual.

This module is the public facade for the ``picard`` sub-package, which splits
the runtime in four concerns:

- ``picard.lscheme``: the bounded relaxed Picard iterate (linear solve loop).
- ``picard.picard``: VI cycles and strict VI obstacle assembly.
- ``picard.diagnostics``: shared math/geometry helpers and record dataclasses.
- ``picard.io``: JSON/CSV diagnostic writers.
"""

from __future__ import annotations

from hydromodpy.solver.boussinesq.runtimes.picard.diagnostics import (
    PicardIterationRecord,
    PicardLschemeOptions,
    PicardViCycleOptions,
    PicardViCycleRecord,
)
from hydromodpy.solver.boussinesq.runtimes.picard.io import (
    PICARD_LSCHEME_FINAL_CELLS_CSV,
    PICARD_LSCHEME_ITERATIONS_CSV,
    PICARD_LSCHEME_SUMMARY_JSON,
    PICARD_VI_CYCLE_SUMMARY_JSON,
    PICARD_VI_CYCLES_CSV,
    write_picard_lscheme_diagnostics,
    write_picard_vi_cycle_diagnostics,
)
from hydromodpy.solver.boussinesq.runtimes.picard.lscheme import bounded_picard_lscheme
from hydromodpy.solver.boussinesq.runtimes.picard.picard import (
    assemble_strict_steady_residual as _assemble_strict_steady_residual,
)
from hydromodpy.solver.boussinesq.runtimes.picard.picard import bounded_picard_vi_cycles

__all__ = [
    "PICARD_LSCHEME_FINAL_CELLS_CSV",
    "PICARD_LSCHEME_ITERATIONS_CSV",
    "PICARD_LSCHEME_SUMMARY_JSON",
    "PICARD_VI_CYCLES_CSV",
    "PICARD_VI_CYCLE_SUMMARY_JSON",
    "PicardIterationRecord",
    "PicardLschemeOptions",
    "PicardViCycleOptions",
    "PicardViCycleRecord",
    "_assemble_strict_steady_residual",
    "bounded_picard_lscheme",
    "bounded_picard_vi_cycles",
    "write_picard_lscheme_diagnostics",
    "write_picard_vi_cycle_diagnostics",
]
