"""Golden-signature regression for the transport MF6 GWT DISV visual-guard example.

The example ``run_visual_guard.py`` produces a fixed numeric signature for each
synthetic fast case (mesh, flow, transport numbers, plume moments, ...). This
test pins those signatures to a committed golden JSON so that any drift in the
synthetic model is caught. It does not run MODFLOW 6; the synthetic mode is a
closed-form generator, so the comparison is deterministic and fast.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "13_transport_mf6_gwt_disv_visual_guard"
MODULE_PATH = EXAMPLE_ROOT / "run_visual_guard.py"
REFERENCE_PATH = (
    Path(__file__).resolve().parent / "golden" / "transport_visual_guard_fast_signatures.json"
)


def _load_guard_module():
    spec = importlib.util.spec_from_file_location("transport_visual_guard", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fast_case(
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


def _fast_cases(guard: Any):
    return [
        _fast_case(
            guard,
            name="fast_01_homogeneous_k_pulse",
            pattern="homogeneous",
            mesh_seed=101,
        ),
        _fast_case(
            guard,
            name="fast_02_longitudinal_channel_kx5_pulse",
            pattern="longitudinal_channel",
            mesh_seed=202,
        ),
        _fast_case(
            guard,
            name="fast_03_transverse_bands_kx5_pulse",
            pattern="transverse_bands",
            mesh_seed=303,
        ),
        _fast_case(
            guard,
            name="fast_04_random_blocks_kx5_pulse",
            pattern="random_blocks",
            mesh_seed=404,
            k_seed=4404,
        ),
        _fast_case(
            guard,
            name="fast_05_homogeneous_constant_upstream",
            pattern="homogeneous",
            mesh_seed=505,
            source_schedule="constant",
            duration_days=650.0,
            n_snapshots=21,
            pulse_end_day=650.0,
        ),
        _fast_case(
            guard,
            name="fast_06_homogeneous_upstream_pulse",
            pattern="homogeneous",
            mesh_seed=606,
            source_schedule="pulse",
            duration_days=650.0,
            n_snapshots=21,
            pulse_end_day=120.0,
        ),
        _fast_case(
            guard,
            name="fast_07_homogeneous_internal_pulse_pe_low",
            pattern="homogeneous",
            mesh_seed=707,
            diffusion_m2_per_day=0.0476,
        ),
        _fast_case(
            guard,
            name="fast_08_homogeneous_internal_pulse_pe_high",
            pattern="homogeneous",
            mesh_seed=808,
            diffusion_m2_per_day=0.00397,
        ),
    ]


def _signature_subset(result: Any) -> dict[str, Any]:
    return {
        "mesh": result.signatures["mesh"],
        "flow": result.signatures["flow"],
        "transport_numbers": result.signatures["transport_numbers"],
        "analytical_comparison": result.signatures["analytical_comparison"],
        "final": result.signatures["time_signatures"][-1],
    }


@pytest.mark.regression
@pytest.mark.fast
def test_fast_synthetic_signatures_match_committed_reference() -> None:
    guard = _load_guard_module()
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    actual = {}
    for case in _fast_cases(guard):
        result = guard.run_synthetic_case(case)
        actual[case.name] = _signature_subset(result)

    assert actual == reference["cases"]
