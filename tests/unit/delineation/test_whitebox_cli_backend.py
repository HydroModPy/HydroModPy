"""Tests for the WhiteboxTools CLI backend placeholder."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.delineation.whitebox_cli_backend import WhiteboxCliBackend


def test_whitebox_cli_backend_is_marked_as_not_implemented() -> None:
    with pytest.raises(NotImplementedError) as excinfo:
        WhiteboxCliBackend()
    assert "whitebox_workflows" in str(excinfo.value) or "synthetic" in str(excinfo.value)


def test_whitebox_cli_backend_exposes_name() -> None:
    assert WhiteboxCliBackend.name == "whitebox_cli"
