"""Unit tests for standalone SGrid + FieldParam discretization workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
import textwrap

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.case_runner import (
    run_discretization_case_from_toml,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SGridConfig
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    discretize_fieldparam_on_sgrid,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_from_config import (
    build_sgrid_from_config,
)


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "sgrid_fieldparam_discretization_signatures.json"
UPDATE_GOLDEN_ENV = "HYDROMODPY_UPDATE_GOLDEN"


def _write_tif(path: Path, arr: np.ndarray) -> None:
    """Write one-band GTiff for tests."""
    data = np.asarray(arr, dtype=np.float32)
    transform = from_origin(0.0, float(data.shape[0]), 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:2154",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)


def _build_sgrid(
    top_path: Path,
    *,
    nlay: int,
    nx: int | None = None,
    ny: int | None = None,
):
    cfg_kwargs: dict[str, object] = {
        "top_path": str(top_path),
        "genmtd_bot": "constant_altitude",
        "zbot": 0.0,
        "genmtd_lay": "constant",
        "nlay": int(nlay),
    }
    if nx is not None and ny is not None:
        cfg_kwargs["plan_discretization_mode"] = "resample_to_shape"
        cfg_kwargs["nx"] = int(nx)
        cfg_kwargs["ny"] = int(ny)
    return build_sgrid_from_config(SGridConfig(**cfg_kwargs))


def _build_test_rasters(tmp_path: Path, *, tag: str = "base") -> tuple[Path, Path]:
    top = np.array(
        [
            [14.0, 14.0, 13.0, 13.0, 12.0, 12.0, 11.0, 11.0],
            [14.5, 14.5, 13.5, 13.5, 12.5, 12.5, 11.5, 11.5],
            [15.0, 15.0, 14.0, 14.0, 13.0, 13.0, 12.0, 12.0],
            [15.5, 15.5, 14.5, 14.5, 13.5, 13.5, 12.5, 12.5],
            [16.0, 16.0, 15.0, 15.0, 14.0, 14.0, 13.0, 13.0],
            [16.5, 16.5, 15.5, 15.5, 14.5, 14.5, 13.5, 13.5],
        ],
        dtype=float,
    )
    geology = np.array(
        [
            [1, 1, 1, 2, 2, 2, 3, 3],
            [1, 1, 1, 2, 2, 2, 3, 3],
            [1, 1, 3, 2, 2, 2, 3, 3],
            [1, 1, 3, 2, 2, 2, 3, 3],
            [1, 1, 1, 2, 2, 2, 3, 3],
            [1, 1, 1, 2, 2, 2, 3, 3],
        ],
        dtype=float,
    )
    top_path = tmp_path / f"top_{tag}.tif"
    geology_path = tmp_path / f"geology_{tag}.tif"
    _write_tif(top_path, top)
    _write_tif(geology_path, geology)
    return top_path, geology_path


def _build_geology_field(geology_path: Path) -> GeologyField:
    return GeologyField.from_dict(
        {
            "id": "field_geology",
            "source": {"path": str(geology_path), "kind": "raster"},
            "cell_samples_per_axis": 8,
        }
    )


def _build_field_param(*, vertical_profile: dict[str, object] | None = None) -> FieldParam:
    kwargs: dict[str, object] = {}
    if vertical_profile is not None:
        kwargs["vertical_profile"] = vertical_profile
    return FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"1": 12.0, "2": 5.0, "3": 1.5},
        field_spatial_id="field_geology",
        **kwargs,
    )


def _run_case(
    tmp_path: Path,
    *,
    nlay: int,
    nx: int | None = None,
    ny: int | None = None,
    vertical_profile: dict[str, object] | None = None,
):
    top_path, geology_path = _build_test_rasters(tmp_path)
    sgrid = _build_sgrid(top_path, nlay=nlay, nx=nx, ny=ny)
    geology_field = _build_geology_field(geology_path)
    field_param = _build_field_param(vertical_profile=vertical_profile)
    result = discretize_fieldparam_on_sgrid(
        geology_field=geology_field,
        field_param=field_param,
        sgrid=sgrid,
    )
    return result, sgrid


def _compute_layer_center_depths(sgrid) -> np.ndarray:
    top_arr = np.asarray(sgrid.top, dtype=float)
    botm = np.asarray(sgrid.botm, dtype=float)
    ztop = np.empty_like(botm, dtype=float)
    ztop[0, :, :] = top_arr
    if botm.shape[0] > 1:
        ztop[1:, :, :] = botm[:-1, :, :]
    return np.maximum(0.0, top_arr[None, :, :] - 0.5 * (ztop + botm))


def _array_stats(arr) -> dict[str, float]:
    values = np.asarray(arr, dtype=float)
    finite = values[np.isfinite(values)]
    return {
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "sum": float(np.sum(finite)),
        "p50": float(np.percentile(finite, 50)),
    }


def _signature_from_result(result) -> dict[str, object]:
    values_2d = np.asarray(result.values_2d, dtype=float)
    values_3d = np.asarray(result.values_3d, dtype=float)
    nlay = int(values_3d.shape[0])
    row_mid = int(values_3d.shape[1] // 2)
    col_mid = int(values_3d.shape[2] // 2)
    return {
        "shape_2d": [int(v) for v in values_2d.shape],
        "shape_3d": [int(v) for v in values_3d.shape],
        "stats_2d": _array_stats(values_2d),
        "stats_3d": _array_stats(values_3d),
        "layer_means": [float(np.mean(values_3d[ilay])) for ilay in range(nlay)],
        "center_profile": [float(v) for v in values_3d[:, row_mid, col_mid]],
    }


def _assert_signature_close(actual: dict[str, object], expected: dict[str, object]) -> None:
    assert actual["shape_2d"] == expected["shape_2d"]
    assert actual["shape_3d"] == expected["shape_3d"]

    for stats_key in ("stats_2d", "stats_3d"):
        actual_stats = actual[stats_key]
        expected_stats = expected[stats_key]
        for k in ("min", "max", "mean", "sum", "p50"):
            assert actual_stats[k] == pytest.approx(expected_stats[k], rel=1e-6, abs=1e-9)

    assert len(actual["layer_means"]) == len(expected["layer_means"])
    assert len(actual["center_profile"]) == len(expected["center_profile"])
    for a, e in zip(actual["layer_means"], expected["layer_means"], strict=True):
        assert a == pytest.approx(e, rel=1e-6, abs=1e-9)
    for a, e in zip(actual["center_profile"], expected["center_profile"], strict=True):
        assert a == pytest.approx(e, rel=1e-6, abs=1e-9)


def test_discretize_fieldparam_on_sgrid_nominal(tmp_path: Path):
    top = np.full((4, 4), 10.0, dtype=float)
    geology = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
        ],
        dtype=float,
    )
    top_path = tmp_path / "top.tif"
    geology_path = tmp_path / "geology.tif"
    _write_tif(top_path, top)
    _write_tif(geology_path, geology)

    sgrid = _build_sgrid(top_path, nlay=1)
    geology_field = GeologyField.from_dict(
        {
            "id": "field_geology",
            "source": {"path": str(geology_path), "kind": "raster"},
            "cell_samples_per_axis": 8,
        }
    )
    field_param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"1": 10.0, "2": 3.0},
        field_spatial_id="field_geology",
    )

    result = discretize_fieldparam_on_sgrid(
        geology_field=geology_field,
        field_param=field_param,
        sgrid=sgrid,
    )
    assert result.values_3d.shape == (1, 4, 4)
    assert result.values_2d.shape == (4, 4)
    assert np.allclose(result.values_2d[:, :2], 10.0)
    assert np.allclose(result.values_2d[:, 2:], 3.0)
    assert np.allclose(result.values_3d[0], result.values_2d)


@pytest.mark.parametrize(
    ("nx", "ny", "nlay"),
    [
        (None, None, 3),
        (6, 5, 4),
        (9, 4, 5),
    ],
)
def test_discretize_fieldparam_on_sgrid_depth_homogeneous_for_varied_discretizations(
    tmp_path: Path,
    nx: int | None,
    ny: int | None,
    nlay: int,
):
    result, sgrid = _run_case(tmp_path, nlay=nlay, nx=nx, ny=ny, vertical_profile={"mode": "none"})
    nrow = int(sgrid.nrow)
    ncol = int(sgrid.ncol)
    assert result.values_2d.shape == (nrow, ncol)
    assert result.values_3d.shape == (nlay, nrow, ncol)
    expected_3d = np.repeat(np.asarray(result.values_2d, dtype=float)[None, :, :], nlay, axis=0)
    assert np.allclose(result.values_3d, expected_3d)


@pytest.mark.parametrize(
    ("nx", "ny", "nlay", "characteristic_depth"),
    [
        (None, None, 3, 10.0),
        (6, 5, 4, 11.0),
        (9, 4, 5, 14.0),
    ],
)
def test_discretize_fieldparam_on_sgrid_exponential_profile_for_varied_discretizations(
    tmp_path: Path,
    nx: int | None,
    ny: int | None,
    nlay: int,
    characteristic_depth: float,
):
    result, sgrid = _run_case(
        tmp_path,
        nlay=nlay,
        nx=nx,
        ny=ny,
        vertical_profile={
            "mode": "exponential",
            "characteristic_depth": float(characteristic_depth),
        },
    )

    depth_center = _compute_layer_center_depths(sgrid)
    expected_factor = np.exp(-depth_center / float(characteristic_depth))
    expected_3d = np.asarray(result.values_2d, dtype=float)[None, :, :] * expected_factor
    assert np.allclose(result.values_3d, expected_3d)

    layer_means = np.asarray([np.mean(np.asarray(result.values_3d[il], dtype=float)) for il in range(nlay)])
    # Exponential profile should produce a strict decrease with layer-center depth.
    assert np.all(np.diff(layer_means) < 0.0)


def test_discretize_fieldparam_on_sgrid_exponential_profile_respects_min_factor(tmp_path: Path):
    result, sgrid = _run_case(
        tmp_path,
        nlay=8,
        nx=7,
        ny=6,
        vertical_profile={
            "mode": "exponential",
            "characteristic_depth": 6.0,
            "min_factor": 0.2,
        },
    )

    depth_center = _compute_layer_center_depths(sgrid)
    expected_factor = np.maximum(np.exp(-depth_center / 6.0), 0.2)
    expected_3d = np.asarray(result.values_2d, dtype=float)[None, :, :] * expected_factor
    assert np.allclose(result.values_3d, expected_3d)
    assert np.min(expected_factor) == pytest.approx(0.2)


def test_discretize_fieldparam_on_sgrid_rejects_mismatching_spatial_id(tmp_path: Path):
    top = np.full((4, 4), 10.0, dtype=float)
    geology = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
        ],
        dtype=float,
    )
    top_path = tmp_path / "top.tif"
    geology_path = tmp_path / "geology.tif"
    _write_tif(top_path, top)
    _write_tif(geology_path, geology)

    sgrid = _build_sgrid(top_path, nlay=1)
    geology_field = GeologyField.from_dict(
        {
            "id": "field_geology",
            "source": {"path": str(geology_path), "kind": "raster"},
        }
    )
    field_param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"1": 10.0, "2": 3.0},
        field_spatial_id="another_field",
    )

    with pytest.raises(ValueError, match="field_param.field_spatial_id"):
        _ = discretize_fieldparam_on_sgrid(
            geology_field=geology_field,
            field_param=field_param,
            sgrid=sgrid,
            strict_field_spatial_id_match=True,
        )


def test_run_discretization_case_from_toml(tmp_path: Path):
    top = np.full((4, 4), 10.0, dtype=float)
    geology = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
        ],
        dtype=float,
    )
    top_path = tmp_path / "top.tif"
    geology_raster_path = tmp_path / "geology.tif"
    _write_tif(top_path, top)
    _write_tif(geology_raster_path, geology)

    case_toml = tmp_path / "discretization_case.toml"
    case_toml.write_text(
        textwrap.dedent(
            f"""
            [case]
            depth = 0.0
            strict_field_spatial_id_match = true
            output_npy = "output_values.npy"
            output_summary_json = "output_summary.json"

            [case.geology]
            id = "field_geology"
            cell_samples_per_axis = 8

            [case.geology.source]
            path = "{geology_raster_path.name}"
            kind = "raster"

            [case.field_param.field]
            id = "K"
            kind = "heterogeneous"

            [case.field_param.field_heterogeneous]
            values_source = "inline"
            values = {{ "1" = 10.0, "2" = 3.0 }}
            field_spatial_id = "field_geology"

            [case.sgrid]
            top_path = "{top_path.name}"
            genmtd_bot = "constant_altitude"
            zbot = 0.0
            genmtd_lay = "constant"
            nlay = 1
            """
        ),
        encoding="utf-8",
    )

    result = run_discretization_case_from_toml(case_toml, section="case")
    assert result.values_3d.shape == (1, 4, 4)
    assert result.values_2d.shape == (4, 4)
    assert np.allclose(result.values_2d[:, :2], 10.0)
    assert np.allclose(result.values_2d[:, 2:], 3.0)

    output_npy = tmp_path / "output_values.npy"
    output_summary = tmp_path / "output_summary.json"
    assert output_npy.exists()
    assert output_summary.exists()

    summary = json.loads(output_summary.read_text(encoding="utf-8"))
    assert summary["shape"] == [4, 4]
    assert summary["shape_3d"] == [1, 4, 4]
    assert summary["nlay"] == 1
    assert summary["field_param_id"] == "K"
    assert summary["geology_field_id"] == "field_geology"


def test_discretization_non_regression_golden_signatures(tmp_path: Path):
    scenarios = [
        {
            "name": "native_none_nlay3",
            "nlay": 3,
            "nx": None,
            "ny": None,
            "vertical_profile": {"mode": "none"},
        },
        {
            "name": "shape_6x5_none_nlay4",
            "nlay": 4,
            "nx": 6,
            "ny": 5,
            "vertical_profile": {"mode": "none"},
        },
        {
            "name": "shape_7x4_exp_nlay4_cd11",
            "nlay": 4,
            "nx": 7,
            "ny": 4,
            "vertical_profile": {"mode": "exponential", "characteristic_depth": 11.0},
        },
        {
            "name": "shape_9x4_exp_nlay5_cd14",
            "nlay": 5,
            "nx": 9,
            "ny": 4,
            "vertical_profile": {"mode": "exponential", "characteristic_depth": 14.0},
        },
    ]

    actual_by_scenario: dict[str, dict[str, object]] = {}
    for scenario in scenarios:
        case_dir = tmp_path / scenario["name"]
        case_dir.mkdir(parents=True, exist_ok=True)
        result, _ = _run_case(
            case_dir,
            nlay=int(scenario["nlay"]),
            nx=scenario["nx"],
            ny=scenario["ny"],
            vertical_profile=scenario["vertical_profile"],
        )
        actual_by_scenario[str(scenario["name"])] = _signature_from_result(result)

    update_golden = os.getenv(UPDATE_GOLDEN_ENV, "0") == "1"
    if update_golden:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        GOLDEN_FILE.write_text(
            json.dumps(actual_by_scenario, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference: {GOLDEN_FILE}. "
            f"Generate it once with {UPDATE_GOLDEN_ENV}=1."
        )

    expected_by_scenario = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    assert set(actual_by_scenario) == set(expected_by_scenario)
    for scenario_name in sorted(actual_by_scenario):
        _assert_signature_close(
            actual=actual_by_scenario[scenario_name],
            expected=expected_by_scenario[scenario_name],
        )
