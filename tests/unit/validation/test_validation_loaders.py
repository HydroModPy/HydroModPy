"""Tests for validation output loader contracts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from validation_cases.shared.loaders import load_npy_dict


def test_legacy_npy_loading_requires_explicit_env_flag(tmp_path: Path) -> None:
    """Archived ``.npy`` payloads are opt-in outside the result store path."""
    path = tmp_path / "watertable_elevation.npy"
    np.save(path, {0: np.array([1.0, 2.0], dtype=float)})

    with pytest.raises(RuntimeError, match="Legacy validation .npy loading is disabled"):
        load_npy_dict(path)


def test_legacy_npy_loading_reads_when_explicitly_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in flag keeps archived pre-v1 artifacts readable."""
    path = tmp_path / "watertable_elevation.npy"
    np.save(path, {0: np.array([1.0, 2.0], dtype=float)})

    monkeypatch.setenv("HYDROMODPY_ALLOW_LEGACY_NPY_VALIDATION", "1")
    payload = load_npy_dict(path)

    np.testing.assert_array_equal(payload[0], np.array([1.0, 2.0], dtype=float))
