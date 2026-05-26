from __future__ import annotations

from pathlib import Path

import numpy as np

from validation_cases.shared.boussinesq_piecewise_strip import (
    aggregate_piecewise_strip_postprocess_fields,
)


def _write_minimal_bundle(bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "nodes.csv").write_text(
        "\n".join(
            [
                "node_id,x,y,z_top,z_bottom",
                "0,0.0,0.0,10.0,0.0",
                "1,2.0,0.0,10.0,0.0",
                "2,0.0,1.0,10.0,0.0",
                "3,2.0,1.0,10.0,0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,z_top_centroid,area_m2,storage_coefficient",
                "0,0.25,0.5,10.0,1.0,0.1",
                "1,0.75,0.5,10.0,1.0,0.1",
                "2,1.25,0.5,12.0,1.0,0.1",
                "3,1.75,0.5,12.0,1.0,0.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_piecewise_postprocess_fields_return_structured_payload_without_rewrite(
    tmp_path: Path,
) -> None:
    postprocess_dir = tmp_path / "_postprocess"
    postprocess_dir.mkdir()
    bundle_dir = tmp_path / "mesh_bundle"
    _write_minimal_bundle(bundle_dir)
    np.save(
        postprocess_dir / "watertable_elevation.npy",
        {0: np.asarray([2.0, 4.0, 6.0, 8.0], dtype=float)},
    )

    fields = aggregate_piecewise_strip_postprocess_fields(
        postprocess_dir,
        bundle_dir=bundle_dir,
        nx=2,
        ny=1,
    )

    assert not (postprocess_dir / "watertable_depth.npy").exists()
    np.testing.assert_allclose(
        fields["watertable_elevation"][0],
        np.asarray([[3.0, 7.0]], dtype=float),
    )
    np.testing.assert_allclose(
        fields["watertable_depth"][0],
        np.asarray([[7.0, 5.0]], dtype=float),
    )
