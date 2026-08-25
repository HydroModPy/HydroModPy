"""Steady 1D validation of the Dupuit seepage limit and its K/R invariance."""

from .comparison import (
    SeepageLimitComparison,
    build_seepage_limit_comparison,
    drain_outflow_ratio,
    head_disagreement_m,
    mask_disagreement_cells,
    run_seepage_limit_comparison,
    run_seepage_limit_sweep,
)
from .plotting import plot_seepage_limit_comparison
from .reference import (
    expected_head_profile_m,
    expected_seepage_mask,
    seepage_limit_position_m,
)

__all__ = [
    "SeepageLimitComparison",
    "build_seepage_limit_comparison",
    "drain_outflow_ratio",
    "expected_head_profile_m",
    "expected_seepage_mask",
    "head_disagreement_m",
    "mask_disagreement_cells",
    "plot_seepage_limit_comparison",
    "run_seepage_limit_comparison",
    "run_seepage_limit_sweep",
    "seepage_limit_position_m",
]
