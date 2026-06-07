"""Tests for irregular-strip projection helpers used by validation cases."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from validation_cases.shared.gmsh_irregular_strip import (
    interpolate_bundle_history_to_structured_grids,
)


def _write_minimal_bundle(bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "nodes.csv").write_text(
        "\n".join(
            [
                "node_id,x,y",
                "0,0.0,0.0",
                "1,2.0,0.0",
                "2,2.0,1.0",
                "3,0.0,1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,area_m2",
                "0,0.25,0.25,1.0",
                "1,0.75,0.75,3.0",
                "2,1.25,0.25,2.0",
                "3,1.75,0.75,2.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_irregular_strip_history_can_collapse_to_row_invariant_x_profile(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    _write_minimal_bundle(bundle_dir)
    history = np.asarray(
        [
            [10.0, 18.0, 30.0, 34.0],
            [20.0, 28.0, 40.0, 44.0],
        ],
        dtype=float,
    )

    projected = interpolate_bundle_history_to_structured_grids(
        history,
        bundle_dir=bundle_dir,
        nx=2,
        ny=3,
        collapse_y_to_x_profile=True,
    )

    expected_profiles = np.asarray(
        [
            [16.0, 32.0],
            [26.0, 42.0],
        ],
        dtype=float,
    )
    assert projected.shape == (2, 3, 2)
    np.testing.assert_allclose(projected[:, 0, :], expected_profiles)
    np.testing.assert_allclose(projected[:, 1, :], expected_profiles)
    np.testing.assert_allclose(projected[:, 2, :], expected_profiles)
    np.testing.assert_allclose(np.std(projected, axis=1), 0.0)
