"""Core building blocks for HydroModPy geographic preprocessing.

Purpose
-------
Provide small, testable modules that each implement one geographic step
(flow products, catchment delineation, domain clipping, zoning, metrics).

How to use this package
-----------------------
- Normal runtime code should keep using ``hydromodpy.spatial.geographic`` as facade.
- Advanced integrations can import specific modules from ``geographic.core``
  when a finer orchestration is required.
"""
