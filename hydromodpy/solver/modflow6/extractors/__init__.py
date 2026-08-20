"""MODFLOW 6 output adapters: solver files → Catalog."""

from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow6.extractors.prt import Modflow6PrtOutputAdapter
from hydromodpy.solver.modflow6.extractors.transport import Modflow6GwtOutputAdapter

__all__ = ["Modflow6GwtOutputAdapter", "Modflow6OutputAdapter", "Modflow6PrtOutputAdapter"]
