"""Temporal discretization utilities for solver workflows."""

from .tmesh_generation import TMeshConfig, TMesh_Generation

# Backward-compatible alias.
TGrid_Generation = TMesh_Generation

__all__ = ["TMeshConfig", "TMesh_Generation", "TGrid_Generation"]

