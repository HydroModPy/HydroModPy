"""Core infrastructure layer for HydroModPy.

Keep this package-level module lightweight: importing ``hydromodpy.core``
should not eagerly pull the full configuration and data-loading stack.
``core`` is the kernel leaf of the import DAG and must not re-export
symbols from sibling layers.
"""

from __future__ import annotations
