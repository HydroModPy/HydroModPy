"""Unit tests for temporal mesh generation helpers."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import uuid

import numpy as np
import pandas as pd
import pytest


def _load_tmesh_module():
    repo_root = Path(__file__).resolve().parents[5]
    module_path = (
        repo_root
        / "hydromodpy"
        / "solver"
        / "utils"
        / "temporal"
        / "tmesh_generation.py"
    )
    module_name = f"_test_tmesh_generation_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeModelTime:
    """Simple stand-in for flopy.discretization.modeltime.ModelTime."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_synthetic_regular_builds_expected_arrays(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    cfg = mod.TMeshConfig(
        genmtd="synthetic_regular",
        flow_regime="transient",
        nper=3,
        lenper=2,
        firstpersteady=True,
        ntsp=2,
        tsmult=1.5,
    )
    builder = mod.TMesh_Generation.from_config(cfg)
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([2.0, 2.0, 2.0]))
    assert np.array_equal(tmesh.nstp, np.array([2, 2, 2]))
    assert np.allclose(tmesh.tsmult, np.array([1.5, 1.5, 1.5]))
    assert np.array_equal(tmesh.steady_state, np.array([True, False, False]))
    assert builder._tmesh_created is True
    assert builder._tgrid_created is True


def test_synthetic_regular_with_seconds_itmuni_keeps_second_lengths(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    cfg = mod.TMeshConfig(
        itmuni="seconds",
        genmtd="synthetic_regular",
        flow_regime="transient",
        nper=2,
        lenper=3600,
        ntsp=1,
        tsmult=1.0,
    )
    builder = mod.TMesh_Generation.from_config(cfg)
    tmesh = builder.run()

    assert np.allclose(tmesh.perlen, np.array([3600.0, 3600.0]))


def test_from_chron_parses_dates_and_computes_perlen(monkeypatch, tmp_path: Path):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n"
        "2020-01-01 00:00:00\t1\n"
        "2020-01-03 00:00:00\t2\n"
        "2020-01-06 00:00:00\t3\n",
        encoding="utf-8",
    )

    builder = mod.TMesh_Generation(
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


def test_synthetic_regular_checks_start_end_window_consistency(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    builder = mod.TMesh_Generation(
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


def test_synthetic_regular_rejects_inconsistent_end_datetime(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    builder = mod.TMesh_Generation(
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


def test_from_chron_respects_explicit_start_end_window(monkeypatch, tmp_path: Path):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n"
        "2020-01-01 00:00:00\t1\n"
        "2020-01-02 00:00:00\t2\n"
        "2020-01-03 00:00:00\t3\n"
        "2020-01-04 00:00:00\t4\n",
        encoding="utf-8",
    )

    builder = mod.TMesh_Generation(
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


def test_from_chron_requires_exact_window_bounds_in_chronicle(monkeypatch, tmp_path: Path):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n"
        "2020-01-01 00:00:00\t1\n"
        "2020-01-02 00:00:00\t2\n"
        "2020-01-03 00:00:00\t3\n",
        encoding="utf-8",
    )

    builder = mod.TMesh_Generation(
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
        _ = mod.TMesh_Generation(config=mod.TMeshConfig(genmtd="unknown"))


def test_invalid_flow_regime_raises():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="steady.*transient"):
        _ = mod.TMesh_Generation(config=mod.TMeshConfig(flow_regime="unknown"))


def test_invalid_nper_raises():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="nper must be > 0"):
        _ = mod.TMesh_Generation(config=mod.TMeshConfig(nper=0))


def test_from_chron_requires_path():
    mod = _load_tmesh_module()
    with pytest.raises(ValueError, match="chron_path is required"):
        _ = mod.TMesh_Generation(config=mod.TMeshConfig(genmtd="from_chron"))


def test_from_chron_requires_strictly_increasing_dates(monkeypatch, tmp_path: Path):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n"
        "2020-01-01 00:00:00\t1\n"
        "2020-01-01 00:00:00\t2\n",
        encoding="utf-8",
    )
    builder = mod.TMesh_Generation(
        config=mod.TMeshConfig(genmtd="from_chron", chron_path=str(chron_path))
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        _ = builder.run()


def test_from_chron_requires_time_column(monkeypatch, tmp_path: Path):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Other\tvalue\n"
        "2020-01-01 00:00:00\t1\n"
        "2020-01-02 00:00:00\t2\n",
        encoding="utf-8",
    )
    builder = mod.TMesh_Generation(
        config=mod.TMeshConfig(genmtd="from_chron", chron_path=str(chron_path))
    )

    with pytest.raises(ValueError, match="not found"):
        _ = builder.run()


def test_from_chron_invalid_date_format_raises(monkeypatch, tmp_path: Path):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    chron_path = tmp_path / "chron.csv"
    chron_path.write_text(
        "Date\tvalue\n"
        "01/31/2020\t1\n"
        "02/01/2020\t2\n",
        encoding="utf-8",
    )
    builder = mod.TMesh_Generation(
        config=mod.TMeshConfig(
            genmtd="from_chron",
            chron_path=str(chron_path),
            chron_dateformat="%Y-%m-%d",
        )
    )

    with pytest.raises(ValueError, match="Failed to parse chronicle dates"):
        _ = builder.run()


def test_ntsp_length_mismatch_raises(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    builder = mod.TMesh_Generation(
        config=mod.TMeshConfig(genmtd="synthetic_regular", nper=3, ntsp=[1, 1])
    )
    with pytest.raises(ValueError, match="ntsp length mismatch"):
        _ = builder.run()


def test_tsmult_must_be_positive(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    with pytest.raises(ValueError, match="tsmult values must be > 0"):
        mod.TMesh_Generation(
            config=mod.TMeshConfig(genmtd="synthetic_regular", nper=2, tsmult=[1.0, 0.0])
        )


def test_changing_property_invalidates_cached_mesh(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", _FakeModelTime)

    builder = mod.TMesh_Generation(config=mod.TMeshConfig(nper=2))
    first = builder.run()
    builder.lenper = 3

    assert builder._tmesh_created is False
    assert builder._tgrid_created is False

    second = builder.run()
    assert first is not second
    assert np.allclose(second.perlen, np.array([3.0, 3.0]))


def test_legacy_genmtd_tgrid_alias():
    mod = _load_tmesh_module()
    builder = mod.TMesh_Generation()

    assert builder.genmtd_tgrid == "synthetic_regular"
    builder.genmtd_tgrid = "synthetic_regular"
    assert builder.genmtd == "synthetic_regular"


def test_run_raises_when_flopy_modeltime_is_unavailable(monkeypatch):
    mod = _load_tmesh_module()
    monkeypatch.setattr(mod, "ModelTime", None)
    builder = mod.TMesh_Generation()

    with pytest.raises(ModuleNotFoundError, match="flopy is required"):
        _ = builder.run()
