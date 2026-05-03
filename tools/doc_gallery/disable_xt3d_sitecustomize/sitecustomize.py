"""Diagnostics hook used by doc-gallery benchmarks to force XT3D off."""

from hydromodpy.solver.modflow6.modflow6 import Modflow6


def _xt3d_disabled(self, solver_mesh=None) -> bool:
    return False


def _xt3d_disabled_mode(self, solver_mesh=None) -> str:
    return "forced_disabled_for_doc_gallery"


Modflow6._xt3d_is_enabled = _xt3d_disabled
Modflow6._xt3d_activation_mode = _xt3d_disabled_mode
