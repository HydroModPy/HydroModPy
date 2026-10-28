"""The outlet delineation on the ramp, frozen as a golden.

``cases/update_geographic_goldens.py`` regenerates this file by its path.
"""

from __future__ import annotations

from pathlib import Path

from tests._helpers.geographic_cases import (
    OUTLET_CATCHMENT,
    assert_delineation_golden,
    delineate_on_fake_backend,
    delineation_signature,
)

GOLDEN = (
    Path(__file__).resolve().parent / "golden" / "catchment_delineation_outlet_contract_golden.json"
)


def test_catchment_delineation_from_outlet_golden(update_goldens, tmp_path, monkeypatch) -> None:
    geo = delineate_on_fake_backend(tmp_path, monkeypatch, OUTLET_CATCHMENT)

    assert_delineation_golden(delineation_signature(geo), GOLDEN, update_goldens)
