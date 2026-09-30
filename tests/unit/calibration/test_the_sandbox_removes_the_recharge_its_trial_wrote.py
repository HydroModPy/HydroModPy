"""A trial's own ``_recharge`` folder lives under its model folder.

:class:`TrialSandbox` already removes the whole model directory on exit (or
keeps it when a solve is retained for a promotion): a ``_recharge`` folder
written inside it, as a trial that samples the recharge does
(:mod:`hydromodpy.solver.modflow6.builders.recharge`, ``§9.2``), goes with it,
with no special-casing needed.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.calibration.runners.sandbox import TrialSandbox
from hydromodpy.solver.modflow6.builders.recharge import TRIAL_RECHARGE_DIRNAME


def _write_recharge_file(scratch: Path, model_name: str) -> Path:
    recharge_dir = scratch / model_name / TRIAL_RECHARGE_DIRNAME
    recharge_dir.mkdir(parents=True)
    (recharge_dir / "rcha_deadbeef.0.bin").write_bytes(b"x" * 32)
    return recharge_dir


class TestSandboxRemovesItsRecharge:
    def test_the_recharge_folder_is_gone_on_exit(self, tmp_path: Path) -> None:
        sandbox = TrialSandbox("cheze", 1, solver_scratch_folder=tmp_path)
        recharge_dir = _write_recharge_file(tmp_path, sandbox.model_name)
        with sandbox:
            assert recharge_dir.is_dir()
        assert not recharge_dir.exists()

    def test_a_kept_solve_keeps_its_recharge(self, tmp_path: Path) -> None:
        sandbox = TrialSandbox("cheze", 2, solver_scratch_folder=tmp_path)
        recharge_dir = _write_recharge_file(tmp_path, sandbox.model_name)
        with sandbox:
            sandbox.keep_outputs()
        assert recharge_dir.is_dir()
