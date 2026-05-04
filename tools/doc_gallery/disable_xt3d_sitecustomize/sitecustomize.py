"""Diagnostics hook used by doc-gallery benchmarks to force XT3D off."""

from hydromodpy.solver.modflow6 import modflow6 as modflow6_module
from hydromodpy.solver.modflow6.builders import solver_options

Modflow6 = modflow6_module.Modflow6


def _xt3d_disabled(self, solver_mesh=None) -> bool:
    return False


def _xt3d_disabled_mode(self, solver_mesh=None) -> str:
    return "forced_disabled_for_doc_gallery"


def _xt3d_disabled_options(self, solver_mesh=None) -> None:
    return None


Modflow6._xt3d_is_enabled = _xt3d_disabled
Modflow6._xt3d_activation_mode = _xt3d_disabled_mode
Modflow6._resolve_xt3d_npf_options = _xt3d_disabled_options
solver_options.xt3d_is_enabled = _xt3d_disabled
solver_options.xt3d_activation_mode = _xt3d_disabled_mode
solver_options.resolve_xt3d_npf_options = _xt3d_disabled_options
modflow6_module.xt3d_is_enabled = _xt3d_disabled
modflow6_module.xt3d_activation_mode = _xt3d_disabled_mode
modflow6_module.resolve_xt3d_npf_options = _xt3d_disabled_options
