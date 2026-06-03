"""Wrapper that re-exports hardware probe from external package.

Requires `validity_frame` to be installed.
"""
try:
    from validity_frame.probes.hardware import HardwareMetrics, HardwareProbe
except Exception as exc:  # pragma: no cover - environment dependent
    raise ImportError(
        "validity_frame external package not found; install it with 'pip install -e validity_frame'"
    ) from exc

__all__ = ["HardwareMetrics", "HardwareProbe"]
