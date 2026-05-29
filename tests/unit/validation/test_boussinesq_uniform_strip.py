from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from validation_cases.shared.boussinesq_uniform_strip import (
    aggregate_triangle_history_to_structured_fields,
)


def _fake_strip_model(workspace: Path) -> SimpleNamespace:
    mesh = SimpleNamespace(
        x_min_m=0.0,
        x_max_m=2.0,
        y_min_m=0.0,
        y_max_m=1.0,
        n_cells=4,
        cell_centroid_x_m=np.asarray([0.25, 0.75, 1.25, 1.75], dtype=float),
        cell_centroid_y_m=np.asarray([0.5, 0.5, 0.5, 0.5], dtype=float),
        z_top_m=np.asarray([10.0, 10.0, 12.0, 12.0], dtype=float),
    )
    state = SimpleNamespace(
        head_history_m=np.asarray(
            [
                [1.0, 1.0, 1.0, 1.0],
                [2.0, 4.0, 6.0, 8.0],
            ],
            dtype=float,
        )
    )
    return SimpleNamespace(state=state, mesh=mesh, full_path=workspace)


def test_uniform_strip_aggregation_returns_fields_without_postprocess_files(
    tmp_path: Path,
) -> None:
    model = _fake_strip_model(tmp_path)

    fields = aggregate_triangle_history_to_structured_fields(model, nx=2, ny=1)

    assert not (tmp_path / "_postprocess").exists()
    np.testing.assert_allclose(
        fields["watertable_elevation"][0],
        np.asarray([[3.0, 7.0]], dtype=float),
    )
    np.testing.assert_allclose(
        fields["watertable_depth"][0],
        np.asarray([[7.0, 5.0]], dtype=float),
    )
