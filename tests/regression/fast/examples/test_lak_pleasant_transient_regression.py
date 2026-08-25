"""Golden-signature regression for the transient multi-layer LAK case.

Pins a compact numeric signature of the HMP DISV LAK build to a committed golden:

* the multi-layer CONNECTIONDATA structure (counts, claktype split, the per-layer
  HORIZONTAL count proving the lake is incised across the top two layers, and a
  stable SHA over the rounded geometry) -- deterministic, no solver run;
* the lake stage at the END of each stress period and the per-period LAK
  water-balance closure from a real MF6 transient run.

Any drift in the builder geometry, the case parameters or the solved transient
fails here. Regenerate with ``pytest --update-goldens`` after an intentional
change. Requires the MF6 binary (``@pytest.mark.mf6``).
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import cast

import pytest

import validation_cases.numerical.transient.lak_pleasant_transient as _case_pkg
from tests.regression.golden_utils import update_or_assert_goldens
from validation_cases.numerical.transient.lak_pleasant_transient.comparison import (
    build_structural_comparison,
    run_pleasant_transient_scenario,
)
from validation_cases.numerical.transient.lak_pleasant_transient.runtime_lak import (
    build_hmp_connectiondata,
)

REFERENCE_PATH = (
    Path(__file__).resolve().parent / "golden" / "lak_pleasant_transient_signatures.json"
)

# Single-source the per-period stage tolerance from the case tolerances.toml
# instead of hard-coding it (tests/TOLERANCES.md is the source of truth).
_TOLERANCES = tomllib.loads(
    (Path(_case_pkg.__file__).resolve().parent / "tolerances.toml").read_text(encoding="utf-8")
)
_PERIOD_STAGE_ABS = float(_TOLERANCES["stage"]["period_stage_abs_error_m"])


def _connectiondata_hash() -> str:
    """Stable SHA-256 over the multi-layer CONNECTIONDATA geometry.

    Rounding the floating geometry to 6 decimals keeps the hash stable across
    platforms while still detecting a real change to the connection set.
    """
    rows = build_hmp_connectiondata()
    serialised = [
        [
            int(row[0]),
            int(row[1]),
            [int(row[2][0]), int(row[2][1])],
            str(row[3]),
            round(float(row[4]), 12),
            round(float(row[5]), 6),
            round(float(row[6]), 6),
            round(float(row[7]), 6),
            round(float(row[8]), 6),
        ]
        for row in rows
    ]
    payload = json.dumps(serialised, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@pytest.mark.regression
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_lak_pleasant_transient_signature_matches_committed_reference(
    tmp_path: Path, update_goldens: bool
) -> None:
    structural = build_structural_comparison()
    scenario = run_pleasant_transient_scenario(workspace=tmp_path)

    actual = {
        "lak_pleasant_transient_expected": {
            "n_connections": structural.n_connections,
            "n_vertical": structural.n_vertical,
            "n_horizontal": structural.n_horizontal,
            "horizontal_layer_0": structural.horizontal_by_layer.get(0, 0),
            "horizontal_layer_1": structural.horizontal_by_layer.get(1, 0),
            "connectiondata_sha256": _connectiondata_hash(),
            "period_stages_m": [round(s, 4) for s in scenario.period_stages_m],
            # ``+ 0.0`` normalises a rounded ``-0.0`` to ``0.0`` so the golden has no
            # platform-dependent sign noise on near-zero budget closures.
            "period_budget_percent": [
                round(p, 5) + 0.0 for p in scenario.hmp.period_budget_percent
            ],
        }
    }

    if update_goldens:
        REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        REFERENCE_PATH.write_text(
            json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return

    expected = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    exp = expected["lak_pleasant_transient_expected"]
    act = actual["lak_pleasant_transient_expected"]

    # Integer structure and the geometry hash must match exactly.
    assert act["n_connections"] == exp["n_connections"]
    assert act["n_vertical"] == exp["n_vertical"]
    assert act["n_horizontal"] == exp["n_horizontal"]
    assert act["horizontal_layer_0"] == exp["horizontal_layer_0"]
    assert act["horizontal_layer_1"] == exp["horizontal_layer_1"]
    assert act["connectiondata_sha256"] == exp["connectiondata_sha256"]

    # Per-period solved scalars match within a small numeric tolerance (solver /
    # BLAS noise). The actual lists come from the typed scenario; the expected ones
    # are cast from the JSON golden.
    act_stages = [round(s, 4) for s in scenario.period_stages_m]
    exp_stages = cast("list[float]", exp["period_stages_m"])
    assert len(act_stages) == len(exp_stages)
    for got, want in zip(act_stages, exp_stages, strict=True):
        assert got == pytest.approx(want, abs=_PERIOD_STAGE_ABS)

    act_budget = [round(p, 5) + 0.0 for p in scenario.hmp.period_budget_percent]
    exp_budget = cast("list[float]", exp["period_budget_percent"])
    for got, want in zip(act_budget, exp_budget, strict=True):
        assert got == pytest.approx(want, abs=1e-2)


def test_update_or_assert_goldens_is_importable() -> None:
    # Guards the shared golden plumbing this test relies on stays importable.
    assert callable(update_or_assert_goldens)
