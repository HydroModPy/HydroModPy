"""End-to-end regression test for examples/07S_short/example_07.py."""

from pathlib import Path

import flopy.utils.binaryfile as bf
import numpy as np
import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    array_stats,
    assert_required_executables,
    assert_stats,
    load_golden_reference,
    run_legacy_example_script,
    write_golden_reference,
)


EXAMPLE_07S_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "07S_short"
    / "example_07.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_07s_short_binary_signatures.json"
)


def _build_binary_signatures(model_ws: Path, model_name: str) -> dict:
    """Create compact signatures from MODFLOW binary outputs (.hds and .cbc)."""
    head_file = model_ws / f"{model_name}.hds"
    budget_file = model_ws / f"{model_name}.cbc"

    hds = bf.HeadFile(str(head_file))
    times = hds.get_times()
    assert times, f"No simulation times found in {head_file}"
    last_time = times[-1]
    head = np.asarray(hds.get_data(totim=last_time), dtype=float)
    finite_head = head[np.isfinite(head)]

    cbc = bf.CellBudgetFile(str(budget_file))
    kstpkper = cbc.get_kstpkper()
    assert kstpkper, f"No stress-period/time-step entries found in {budget_file}"
    last_kstpkper = kstpkper[-1]

    drains = cbc.get_data(text="DRAINS", kstpkper=last_kstpkper)
    const_head = cbc.get_data(text="CONSTANT HEAD", kstpkper=last_kstpkper)
    recharge = cbc.get_data(text="RECHARGE", kstpkper=last_kstpkper)

    return {
        "head_signature": {
            "shape": list(head.shape),
            "n_times": len(times),
            "last_time": float(last_time),
            "stats": array_stats(head),
            "sum": float(finite_head.sum()) if finite_head.size > 0 else None,
        },
        "budget_signature": {
            "n_kstpkper": len(kstpkper),
            "last_kstpkper": [int(last_kstpkper[0]), int(last_kstpkper[1])],
            "drains_sum": float(np.asarray(drains[0]["q"], dtype=float).sum()),
            "constant_head_sum": float(np.asarray(const_head[0]["q"], dtype=float).sum()),
            "recharge_sum": float(np.asarray(recharge[0], dtype=float).sum()),
        },
    }


def _assert_binary_signatures(actual: dict, expected: dict) -> None:
    """Compare binary signatures with numerical tolerance."""
    actual_head = actual["head_signature"]
    expected_head = expected["head_signature"]
    assert actual_head["shape"] == expected_head["shape"]
    assert actual_head["n_times"] == expected_head["n_times"]
    assert actual_head["last_time"] == pytest.approx(expected_head["last_time"], rel=1e-6, abs=1e-9)
    assert_stats(actual_head["stats"], expected_head["stats"])
    if expected_head["sum"] is None:
        assert actual_head["sum"] is None
    else:
        assert actual_head["sum"] == pytest.approx(expected_head["sum"], rel=1e-4, abs=1e-6)

    actual_budget = actual["budget_signature"]
    expected_budget = expected["budget_signature"]
    assert actual_budget["n_kstpkper"] == expected_budget["n_kstpkper"]
    assert actual_budget["last_kstpkper"] == expected_budget["last_kstpkper"]
    assert actual_budget["drains_sum"] == pytest.approx(expected_budget["drains_sum"], rel=1e-4, abs=1e-6)
    assert actual_budget["constant_head_sum"] == pytest.approx(
        expected_budget["constant_head_sum"], rel=1e-4, abs=1e-6
    )
    assert actual_budget["recharge_sum"] == pytest.approx(expected_budget["recharge_sum"], rel=1e-4, abs=1e-6)


@pytest.mark.regression
@pytest.mark.fast
def test_example_07s_short_regression_on_binary_outputs(tmp_path, update_goldens):
    """Run example_07S, then compare (or refresh) binary signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_07s_short_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_07S_SCRIPT,
        out_path=out_path,
        stop_method="processing_modflow",
        expected_stop_calls=1,
        timeout=5400,
    )

    model_name = "default_weekly_mperday_split"
    model_ws = out_path / "07S_short" / "results_simulations" / model_name
    actual = _build_binary_signatures(model_ws, model_name)

    if update_goldens:
        write_golden_reference(GOLDEN_REFERENCE_FILE, actual)
        return

    expected = load_golden_reference(GOLDEN_REFERENCE_FILE)
    _assert_binary_signatures(actual, expected)
