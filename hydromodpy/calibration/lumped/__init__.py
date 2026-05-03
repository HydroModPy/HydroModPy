"""Lumped catchment models used as calibration targets.

GR4J lives here because it never goes through the staged flow runner: it
runs in RAM and is driven directly by the calibration bridge. The solver
layer is reserved for backends that produce on-disk simulation artifacts
(MODFLOW 6, MODFLOW-NWT, Boussinesq).
"""

from hydromodpy.calibration.lumped.gr4j_adapter import Gr4jAdapter
from hydromodpy.calibration.lumped.gr4j_flow import Gr4jFlowExtractor

__all__ = ["Gr4jAdapter", "Gr4jFlowExtractor"]
