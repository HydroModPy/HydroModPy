from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.allow_subprocess
def test_every_config_field_carries_a_profile_tag() -> None:
    # A fresh interpreter, because the audit walks every model class loaded so far.
    done = subprocess.run(
        [sys.executable, "-m", "tools.audit_profile_coverage"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
