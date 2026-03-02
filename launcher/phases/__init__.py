from launcher.phases.setup import _run_setup
from launcher.phases.data import _run_data
from launcher.phases.flow import _run_flow
from launcher.phases.particles import _run_particles
from launcher.phases.transport import _run_transport

PHASE_FN = {
    "setup":     _run_setup,
    "data":      _run_data,
    "flow":      _run_flow,
    "particles": _run_particles,
    "transport": _run_transport,
}

__all__ = ["PHASE_FN"]
