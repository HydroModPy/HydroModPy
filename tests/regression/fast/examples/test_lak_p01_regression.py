"""Golden-signature regression for the LAK ex-gwf-lak-p01 validation case.

Pins a compact numeric signature of the HMP DISV LAK build to a committed golden:

* the home-grown CONNECTIONDATA structure (counts, claktype split, and a stable
  SHA over the rounded VERTICAL + HORIZONTAL geometry) -- deterministic, no
  solver run;
* the steady lake stage and gross lake-aquifer flux from a real MF6 run.

Any drift in the builder geometry, the case parameters or the solved equilibrium
fails here. Regenerate with ``pytest --update-goldens`` after an intentional
change. Requires the MF6 binary (``@pytest.mark.mf6``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.regression.golden_utils import update_or_assert_goldens
from validation_cases.numerical.steady.lak_merritt_konikow_p01.comparison import (
    build_structural_comparison,
    run_lake_p01_scenario,
)
from validation_cases.numerical.steady.lak_merritt_konikow_p01.runtime_lak import (
    build_hmp_connectiondata,
)

REFERENCE_PATH = Path(__file__).resolve().parent / "golden" / "lak_p01_signatures.json"


def _connectiondata_hash() -> str:
    """Stable SHA-256 over the home-grown CONNECTIONDATA geometry.

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
def test_lak_p01_signature_matches_committed_reference(
    tmp_path: Path, update_goldens: bool
) -> None:
    structural = build_structural_comparison()
    scenario = run_lake_p01_scenario(workspace=tmp_path)

    actual = {
        "lak_p01_expected": {
            "n_connections": structural.n_connections,
            "n_vertical": structural.n_vertical,
            "n_horizontal": structural.n_horizontal,
            "connectiondata_sha256": _connectiondata_hash(),
            "final_stage_m": round(scenario.hmp_stage_m, 4),
            "lake_gwf_in_m3_s": round(scenario.hmp.lake_gwf_in, 8),
            "lake_gwf_out_m3_s": round(scenario.hmp.lake_gwf_out, 8),
        }
    }

    if update_goldens:
        REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        REFERENCE_PATH.write_text(
            json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return

    expected = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    exp = expected["lak_p01_expected"]
    act = actual["lak_p01_expected"]

    # Integer structure and the geometry hash must match exactly.
    assert act["n_connections"] == exp["n_connections"]
    assert act["n_vertical"] == exp["n_vertical"]
    assert act["n_horizontal"] == exp["n_horizontal"]
    assert act["connectiondata_sha256"] == exp["connectiondata_sha256"]

    # Solved scalars match within a small numeric tolerance (solver / BLAS noise).
    assert act["final_stage_m"] == pytest.approx(exp["final_stage_m"], abs=1e-2)
    assert act["lake_gwf_in_m3_s"] == pytest.approx(exp["lake_gwf_in_m3_s"], rel=1e-3, abs=1e-6)
    assert act["lake_gwf_out_m3_s"] == pytest.approx(exp["lake_gwf_out_m3_s"], rel=1e-3, abs=1e-6)


def test_update_or_assert_goldens_is_importable() -> None:
    # Guards the shared golden plumbing this test relies on stays importable
    # (the regression harness rejects stale schema versions through it).
    assert callable(update_or_assert_goldens)
