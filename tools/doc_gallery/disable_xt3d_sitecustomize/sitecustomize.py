"""Diagnostics hook used by doc-gallery benchmarks to force XT3D off."""

from __future__ import annotations

import importlib
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder
from types import ModuleType

TARGET_MODULE = "hydromodpy.solver.modflow6.modflow6"


def _xt3d_disabled(self, solver_mesh=None) -> bool:
    return False


def _xt3d_disabled_mode(self, solver_mesh=None) -> str:
    return "forced_disabled_for_doc_gallery"


def _patch_module(module: ModuleType) -> None:
    modflow6 = getattr(module, "Modflow6", None)
    if modflow6 is None:
        return
    modflow6._xt3d_is_enabled = _xt3d_disabled
    modflow6._xt3d_activation_mode = _xt3d_disabled_mode


class _PatchAfterLoad(Loader):
    def __init__(self, wrapped: Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):
        create_module = getattr(self._wrapped, "create_module", None)
        if create_module is None:
            return None
        return create_module(spec)

    def exec_module(self, module: ModuleType) -> None:
        self._wrapped.exec_module(module)
        _patch_module(module)


class _Xt3dPatchFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != TARGET_MODULE:
            return None
        spec = PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _PatchAfterLoad(spec.loader)
        return spec


if TARGET_MODULE in sys.modules:
    _patch_module(sys.modules[TARGET_MODULE])
else:
    sys.meta_path.insert(0, _Xt3dPatchFinder())

# Keep a visible flag for subprocess diagnostics.
sys._hydromodpy_xt3d_forced_disabled = True
