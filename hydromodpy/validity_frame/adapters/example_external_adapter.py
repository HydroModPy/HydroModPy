from __future__ import annotations

from typing import Any

from hydromodpy.validity_frame.probes.base import BaseProbe


class ExampleExternalAdapter(BaseProbe):
    """Example adapter for an external scientific model. This file demonstrates
    how to adapt a model instance into the probe interface without touching
    the rest of the validity_frame package.
    """

    def __init__(self, model: Any):
        self.model = model

    def role(self) -> str:
        return "solver"

    def collect(self, source: Any = None) -> dict:
        # Source may be provided by the collector; fall back to the wrapped model.
        src = source or self.model
        return {
            "solver_name": getattr(src, "name", getattr(src, "__class__", type(src)).__name__),
            "iterations": getattr(src, "n_steps", getattr(src, "iterations", None)),
            "converged": getattr(src, "converged", None),
            "solver_status": getattr(src, "status", None),
        }
