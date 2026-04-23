"""MODFLOW-NWT output adapters: solver files → SimulationCatalog."""

from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter
from hydromodpy.solver.modflow_nwt.extractors.modpath import ModpathOutputAdapter
from hydromodpy.solver.modflow_nwt.extractors.mt3dms import Mt3dmsOutputAdapter

__all__ = ["ModflowNwtOutputAdapter", "ModpathOutputAdapter", "Mt3dmsOutputAdapter"]
