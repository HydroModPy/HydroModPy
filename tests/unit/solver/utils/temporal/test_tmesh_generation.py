"""Unit tests for temporal mesh generation helpers."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _load_tmesh_module():
    repo_root = Path(__file__).resolve().parents[5]
    module_path = repo_root / "hydromodpy" / "solver" / "utils" / "temporal" / "tmesh_generation.py"
    module_name = f"_test_tmesh_generation_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_synthetic_regular_builds_expected_arrays():
    mod = _load_tmesh_module()

    cfg = mod.TMeshConfig(
        genmtd="synthetic_regular",
        flow_regime="transient",
        nper=3,
        lenper=2,
        firstpersteady=True,
        ntsp=2,
        tsmult=1.5,
    )
    builder = mod.TmeshGenerator.from_config(cfg)
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([2.0, 2.0, 2.0]))
    assert np.array_equal(tmesh.nstp, np.array([2, 2, 2]))
    assert np.allclose(tmesh.tsmult, np.array([1.5, 1.5, 1.5]))
    assert np.array_equal(tmesh.steady_state, np.array([True, False, False]))
    assert builder._tmesh_created is True


def test_synthetic_regular_with_seconds_itmuni_keeps_second_lengths():
    mod = _load_tmesh_module()

    cfg = mod.TMeshConfig(
        itmuni="seconds",
        genmtd="synthetic_regular",
        flow_regime="transient",
        nper=2,
        lenper=3600,
        ntsp=1,
        tsmult=1.0,
    )
    builder = mod.TmeshGenerator.from_config(cfg)
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([3600.0, 3600.0]))


def test_from_chron_parses_dates_and_computes_perlen(tmp_path: Path):
    mod = _load_tmesh_module()

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n2020-01-01 00:00:00\t1\n2020-01-03 00:00:00\t2\n2020-01-06 00:00:00\t3\n",
        encoding="utf-8",
    )

    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(
            genmtd="from_chron",
            chron_path=str(chron_path),
            flow_regime="steady",
        )
    )
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([2.0, 3.0]))
    assert pd.Timestamp(tmesh.start_datetime) == pd.Timestamp("2020-01-01 00:00:00")
    assert np.array_equal(tmesh.steady_state, np.array([True, True]))


def test_synthetic_regular_checks_start_end_window_consistency():
    mod = _load_tmesh_module()

    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(
            genmtd="synthetic_regular",
            flow_regime="transient",
            nper=3,
            lenper=2,
            start_datetime="2020-01-01 00:00:00",
            end_datetime="2020-01-07 00:00:00",
        )
    )
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([2.0, 2.0, 2.0]))
    assert pd.Timestamp(tmesh.start_datetime) == pd.Timestamp("2020-01-01 00:00:00")


def test_synthetic_regular_rejects_inconsistent_end_datetime():
    mod = _load_tmesh_module()

    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(
            genmtd="synthetic_regular",
            flow_regime="transient",
            nper=3,
            lenper=2,
            start_datetime="2020-01-01 00:00:00",
            end_datetime="2020-01-08 00:00:00",
        )
    )

    with pytest.raises(ValueError, match="window mismatch"):
        _ = builder.run()


def test_from_chron_respects_explicit_start_end_window(tmp_path: Path):
    mod = _load_tmesh_module()

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n"
        "2020-01-01 00:00:00\t1\n"
        "2020-01-02 00:00:00\t2\n"
        "2020-01-03 00:00:00\t3\n"
        "2020-01-04 00:00:00\t4\n",
        encoding="utf-8",
    )

    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(
            genmtd="from_chron",
            chron_path=str(chron_path),
            start_datetime="2020-01-02 00:00:00",
            end_datetime="2020-01-04 00:00:00",
        )
    )
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([1.0, 1.0]))
    assert pd.Timestamp(tmesh.start_datetime) == pd.Timestamp("2020-01-02 00:00:00")


def test_from_chron_requires_exact_window_bounds_in_chronicle(tmp_path: Path):
    mod = _load_tmesh_module()

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n2020-01-01 00:00:00\t1\n2020-01-02 00:00:00\t2\n2020-01-03 00:00:00\t3\n",
        encoding="utf-8",
    )

    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(
            genmtd="from_chron",
            chron_path=str(chron_path),
            start_datetime="2020-01-01 12:00:00",
            end_datetime="2020-01-03 00:00:00",
        )
    )

    with pytest.raises(ValueError, match="exactly match chronicle timestamps"):
        _ = builder.run()


def test_invalid_genmtd_raises():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="synthetic_regular.*from_chron"):
        _ = mod.TmeshGenerator(config=mod.TMeshConfig(genmtd="unknown"))


def test_invalid_flow_regime_raises():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="steady.*transient"):
        _ = mod.TmeshGenerator(config=mod.TMeshConfig(flow_regime="unknown"))


def test_invalid_nper_raises():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="greater than 0"):
        _ = mod.TmeshGenerator(config=mod.TMeshConfig(nper=0))


def test_from_chron_requires_path():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="chron_path is required"):
        _ = mod.TmeshGenerator(config=mod.TMeshConfig(genmtd="from_chron"))


def test_from_chron_requires_strictly_increasing_dates(tmp_path: Path):
    mod = _load_tmesh_module()

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n2020-01-01 00:00:00\t1\n2020-01-01 00:00:00\t2\n",
        encoding="utf-8",
    )
    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(genmtd="from_chron", chron_path=str(chron_path))
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        _ = builder.run()


def test_from_chron_requires_time_column(tmp_path: Path):
    mod = _load_tmesh_module()

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Other\tvalue\n2020-01-01 00:00:00\t1\n2020-01-02 00:00:00\t2\n",
        encoding="utf-8",
    )
    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(genmtd="from_chron", chron_path=str(chron_path))
    )

    with pytest.raises(ValueError, match="not found"):
        _ = builder.run()


def test_from_chron_invalid_date_format_raises(tmp_path: Path):
    mod = _load_tmesh_module()

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n01/31/2020\t1\n02/01/2020\t2\n",
        encoding="utf-8",
    )
    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(
            genmtd="from_chron",
            chron_path=str(chron_path),
            chron_dateformat="%Y-%m-%d",
        )
    )

    with pytest.raises(ValueError, match="Failed to parse chronicle dates"):
        _ = builder.run()


def test_ntsp_length_mismatch_raises():
    mod = _load_tmesh_module()

    builder = mod.TmeshGenerator(
        config=mod.TMeshConfig(genmtd="synthetic_regular", nper=3, ntsp=[1, 1])
    )
    with pytest.raises(ValueError, match="ntsp length mismatch"):
        _ = builder.run()


def test_tsmult_must_be_positive():
    mod = _load_tmesh_module()

    with pytest.raises(ValueError, match="tsmult values must be > 0"):
        mod.TmeshGenerator(
            config=mod.TMeshConfig(genmtd="synthetic_regular", nper=2, tsmult=[1.0, 0.0])
        )


def test_changing_property_invalidates_cached_mesh():
    mod = _load_tmesh_module()

    builder = mod.TmeshGenerator(config=mod.TMeshConfig(nper=2))
    first = builder.run()
    builder.lenper = 3

    assert builder._tmesh_created is False

    second = builder.run()
    assert first is not second
    assert np.allclose(second.perlen, np.array([3.0, 3.0]))


def test_run_returns_native_time_grid_with_derived_vectors():
    mod = _load_tmesh_module()
    cfg = mod.TMeshConfig(
        genmtd="synthetic_regular",
        flow_regime="transient",
        nper=3,
        lenper=2,
        firstpersteady=False,
        ntsp=1,
        tsmult=1.0,
        start_datetime="2020-01-01 00:00:00",
        end_datetime="2020-01-07 00:00:00",
    )
    builder = mod.TmeshGenerator.from_config(cfg)
    tmesh = builder.run()

    assert isinstance(tmesh, mod.TimeGrid)
    assert tmesh.time_units == "d"
    assert np.allclose(tmesh.totim, np.array([2.0, 4.0, 6.0]))
    assert len(tmesh.datetimes) == 3
    assert tmesh.datetimes[0] == pd.Timestamp("2020-01-03 00:00:00")
    assert tmesh.datetimes[-1] == pd.Timestamp("2020-01-07 00:00:00")
