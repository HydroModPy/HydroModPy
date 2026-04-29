"""Bootstrap helper that resolves HydroModPyConfig forward references.

Lives at the top level so the ``core/`` package stays a leaf of the import
DAG: sibling configs from ``physics/``, ``solver/``, ``spatial/``, ``data/``,
``simulation/``, ``display/``, ``analysis/``, ``calibration/``, and
``workflow/`` are imported here, never from ``core/config/``.
"""

from __future__ import annotations

_BOOTSTRAPPED = False


def _rebuild_forward_refs() -> None:
    """Inject sibling configs into ``hydromodpy_config`` and rebuild the model.

    Pydantic resolves forward references at ``model_rebuild()`` time by name
    lookup against the defining module's globals, so the sibling classes are
    written into ``hydromodpy.core.config.hydromodpy_config.__dict__``.
    """
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.core.config import hydromodpy_config as cfg_module
    from hydromodpy.data.data_managers_config import DataManagersConfig
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.overview.config import OverviewSection
    from hydromodpy.physics.flow.flow_config import FlowConfig
    from hydromodpy.physics.transport.transport_config import TransportConfig
    from hydromodpy.simulation.planning.config import SimulationConfig
    from hydromodpy.solver.base.solver_config import SolverConfig
    from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
    from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
    from hydromodpy.spatial.domain.domain_config import DomainConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig

    cfg_module.__dict__.update(
        CapabilityGalleryConfig=CapabilityGalleryConfig,
        CalibrationConfig=CalibrationConfig,
        DataManagersConfig=DataManagersConfig,
        DisplayConfig=DisplayConfig,
        FlowConfig=FlowConfig,
        TransportConfig=TransportConfig,
        SimulationConfig=SimulationConfig,
        SolverConfig=SolverConfig,
        Modflow6Config=Modflow6Config,
        ModflowConfig=ModflowConfig,
        DomainConfig=DomainConfig,
        GeographicConfig=GeographicConfig,
        MeshCatchmentConfig=MeshCatchmentConfig,
        OverviewSection=OverviewSection,
    )
    cfg_module.HydroModPyConfig.model_rebuild()


def bootstrap() -> None:
    """Resolve HydroModPyConfig forward references. Idempotent."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _rebuild_forward_refs()
    _BOOTSTRAPPED = True
