"""Pydantic helpers shared by every HydroModPy configuration model.

Hosts the strict ``HydroModelBase`` root, the ``Profile`` enum, the
``VisibleWhen`` field-visibility tag, and the introspection / schema export
helpers that operate on these primitives. None of the symbols here carry
hydrology-specific behavior: they are pure Pydantic foundations consumed
by every sub-config in the codebase.

Layer rule: this sub-package may import only ``pydantic``, the standard
library, and ``hydromodpy.core.*``.
"""
