"""Patch test: steady uniform flow on a strip of skewed triangles."""

from .comparison import (
    PatchTestComparison,
    build_patch_test_comparison,
    run_patch_test_comparison,
    uniform_flow_head,
)

__all__ = [
    "PatchTestComparison",
    "build_patch_test_comparison",
    "run_patch_test_comparison",
    "uniform_flow_head",
]
