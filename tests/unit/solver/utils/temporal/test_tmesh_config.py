"""Unit tests for temporal-mesh Pydantic config and TOML loader."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import uuid

import pytest


def _load_tmesh_config_module():
    repo_root = Path(__file__).resolve().parents[5]
    module_path = (
        repo_root
        / "hydromodpy"
        / "solver"
        / "utils"
        / "temporal"
        / "tmesh_config.py"
    )
    module_name = f"_test_tmesh_config_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_from_mapping_accepts_valid_synthetic_payload():
    mod = _load_tmesh_config_module()

    cfg = mod.TMeshConfigModel.from_mapping(
        {
            "tmesh": {
                "itmuni": "d",
                "flow_regime": "transient",
                "genmtd": "synthetic_regular",
                "nper": 3,
                "lenper": 2,
                "firstpersteady": True,
                "ntsp": [1, 2, 1],
                "tsmult": 1.2,
            }
        }
    )

    payload = cfg.to_builder_kwargs()
    assert payload["genmtd"] == "synthetic_regular"
    assert payload["flow_regime"] == "transient"
    assert payload["nper"] == 3
    assert payload["lenper"] == 2.0
    assert payload["ntsp"] == [1, 2, 1]
    assert payload["tsmult"] == 1.2


def test_from_toml_resolves_relative_chron_path(tmp_path: Path):
    mod = _load_tmesh_config_module()

    chron = tmp_path / "chron.csv"
    chron.write_text("Date\n2020-01-01 00:00:00\n2020-01-02 00:00:00\n", encoding="utf-8")

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[tmesh]\n"
        "genmtd = \"from_chron\"\n"
        "flow_regime = \"transient\"\n"
        "chron_path = \"chron.csv\"\n",
        encoding="utf-8",
    )

    cfg = mod.TMeshConfigModel.from_toml(toml_path)
    assert Path(cfg.chron_path).resolve() == chron.resolve()


def test_from_toml_raises_for_missing_section(tmp_path: Path):
    mod = _load_tmesh_config_module()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text("[other]\nvalue = 1\n", encoding="utf-8")

    with pytest.raises(KeyError, match="Missing TOML section"):
        _ = mod.TMeshConfigModel.from_toml(toml_path, section="tmesh")


def test_from_mapping_raises_when_from_chron_without_path():
    mod = _load_tmesh_config_module()

    with pytest.raises(ValueError, match="chron_path is required"):
        _ = mod.TMeshConfigModel.from_mapping(
            {
                "genmtd": "from_chron",
                "flow_regime": "transient",
            }
        )


def test_validate_lists_require_positive_values():
    mod = _load_tmesh_config_module()

    with pytest.raises(ValueError, match="ntsp values must be > 0"):
        _ = mod.TMeshConfigModel.from_mapping(
            {
                "genmtd": "synthetic_regular",
                "flow_regime": "steady",
                "nper": 2,
                "lenper": 1,
                "ntsp": [1, 0],
            }
        )

    with pytest.raises(ValueError, match="tsmult values must be > 0"):
        _ = mod.TMeshConfigModel.from_mapping(
            {
                "genmtd": "synthetic_regular",
                "flow_regime": "steady",
                "nper": 2,
                "lenper": 1,
                "tsmult": [1.0, -0.5],
            }
        )


def test_load_tmesh_toml_returns_normalized_dict(tmp_path: Path):
    mod = _load_tmesh_config_module()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[tmesh]\n"
        "itmuni = \"d\"\n"
        "flow_regime = \"steady\"\n"
        "genmtd = \"synthetic_regular\"\n"
        "nper = 4\n"
        "lenper = 1\n",
        encoding="utf-8",
    )

    payload = mod.load_tmesh_toml(toml_path)
    assert payload["flow_regime"] == "steady"
    assert payload["genmtd"] == "synthetic_regular"
    assert payload["nper"] == 4
    assert payload["lenper"] == 1.0


def test_legacy_sim_state_key_is_rejected():
    mod = _load_tmesh_config_module()

    with pytest.raises(ValueError):
        _ = mod.TMeshConfigModel.from_mapping(
            {
                "tmesh": {
                    "sim_state": "steady",
                    "genmtd": "synthetic_regular",
                    "nper": 1,
                    "lenper": 1,
                }
            }
        )
