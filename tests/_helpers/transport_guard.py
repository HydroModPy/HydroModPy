"""Load the visual-guard transport example and build its fast synthetic cases.

The regression signatures and the mesh diagnostics read the same numeric cases
of ``examples/projects/13_transport_mf6_gwt_disv_visual_guard``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "projects"
    / "13_transport_mf6_gwt_disv_visual_guard"
    / "run_visual_guard.py"
)


def load_guard_module():
    spec = importlib.util.spec_from_file_location("transport_visual_guard", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fast_case(
    guard: Any,
    *,
    name: str,
    pattern: str,
    mesh_seed: int,
    k_seed: int | None = None,
    source_schedule: str = "internal_pulse",
    duration_days: float = 650.0,
    n_snapshots: int = 21,
    pulse_end_day: float = 0.0,
    diffusion_m2_per_day: float = 0.0119,
):
    return guard.CaseConfig(
        name=name,
        title=name,
        description="Fast numeric transport regression case without HTML output.",
        domain=guard.DomainConfig(
            length_m=120.0,
            width_m=24.0,
            nx=32,
            ny=8,
            perturbation_fraction=0.08,
            seed=mesh_seed,
            max_area_ratio=2.20,
        ),
        flow=guard.FlowConfig(
            head_left_m=3.6,
            head_right_m=0.0,
            hydraulic_conductivity_m_per_day=1.0,
            hydraulic_conductivity_pattern=pattern,
            hydraulic_conductivity_factor=5.0,
            hydraulic_conductivity_seed=k_seed,
            porosity=0.30,
        ),
        transport=guard.TransportConfig(
            duration_days=duration_days,
            n_snapshots=n_snapshots,
            source_concentration=1.0,
            source_schedule=source_schedule,
            pulse_end_day=pulse_end_day,
            pulse_center_m=35.0,
            pulse_width_m=2.0,
            pulse_y_center_m=12.0,
            pulse_y_width_m=4.0,
            longitudinal_dispersivity_m=0.0,
            transverse_dispersivity_m=0.0,
            diffusion_m2_per_day=diffusion_m2_per_day,
        ),
        source_path=Path("<in-memory-fast-transport-case>"),
    )


def fast_cases(guard: Any):
    return [
        fast_case(
            guard,
            name="fast_01_homogeneous_k_pulse",
            pattern="homogeneous",
            mesh_seed=101,
        ),
        fast_case(
            guard,
            name="fast_02_longitudinal_channel_kx5_pulse",
            pattern="longitudinal_channel",
            mesh_seed=202,
        ),
        fast_case(
            guard,
            name="fast_03_transverse_bands_kx5_pulse",
            pattern="transverse_bands",
            mesh_seed=303,
        ),
        fast_case(
            guard,
            name="fast_04_random_blocks_kx5_pulse",
            pattern="random_blocks",
            mesh_seed=404,
            k_seed=4404,
        ),
        fast_case(
            guard,
            name="fast_05_homogeneous_constant_upstream",
            pattern="homogeneous",
            mesh_seed=505,
            source_schedule="constant",
            duration_days=650.0,
            n_snapshots=21,
            pulse_end_day=650.0,
        ),
        fast_case(
            guard,
            name="fast_06_homogeneous_upstream_pulse",
            pattern="homogeneous",
            mesh_seed=606,
            source_schedule="pulse",
            duration_days=650.0,
            n_snapshots=21,
            pulse_end_day=120.0,
        ),
        fast_case(
            guard,
            name="fast_07_homogeneous_internal_pulse_pe_low",
            pattern="homogeneous",
            mesh_seed=707,
            diffusion_m2_per_day=0.0476,
        ),
        fast_case(
            guard,
            name="fast_08_homogeneous_internal_pulse_pe_high",
            pattern="homogeneous",
            mesh_seed=808,
            diffusion_m2_per_day=0.00397,
        ),
    ]
