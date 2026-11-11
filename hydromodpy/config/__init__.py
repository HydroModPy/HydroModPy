"""Application-level configuration API.

``HydroModPyConfig`` assembles the full user-facing TOML tree, so it sits above
``core``. Per-layer sub-section configs live in their own packages (e.g.
``hydromodpy.calibration.config:CalibrationConfig``).
"""
