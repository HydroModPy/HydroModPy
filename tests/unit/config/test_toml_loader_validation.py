from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def test_load_toml_with_base_config_rejects_cycles(tmp_path: Path) -> None:
    first_path = tmp_path / "first.toml"
    second_path = tmp_path / "second.toml"

    first_path.write_text('base_config = "second.toml"\n', encoding="utf-8")
    second_path.write_text('base_config = "first.toml"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="circular base_config chain"):
        load_toml_with_base_config(first_path)


def test_from_toml_requires_workspace_project_root(tmp_path: Path) -> None:
    path = tmp_path / "missing_workspace.toml"
    path.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"\[workspace\]\.project_root is required"):
        HydroModPyConfig.from_toml(path)


def test_from_toml_rejects_scalar_workflow(tmp_path: Path) -> None:
    path = tmp_path / "scalar_workflow.toml"
    path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[workspace]",
                f'project_root = "{tmp_path / "demo"}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\[workflow\]"):
        HydroModPyConfig.from_toml(path)


def test_workspace_rejects_filename_safe_windows_path_tokens() -> None:
    drive_token = chr(0xF03A)
    separator_token = chr(0xF05C)
    encoded_path = (
        f"C{drive_token}{separator_token}codes{separator_token}HydroModPy{separator_token}outputs"
    )

    with pytest.raises(ValueError, match="encoded as a safe filename"):
        HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "simulation"},
                "workspace": {"project_root": encoded_path},
                "geographic": {"source_mode": "synthetic"},
            }
        )


def test_hydromodpy_config_rejects_unknown_flow_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "unknown_flow.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                f'project_root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[flow]",
                "typo_runtime = true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Unknown TOML key\(s\) in \[flow\]"):
        HydroModPyConfig.from_toml(config_path)


def test_hydromodpy_config_rejects_unknown_workflow(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown-workflow"):
        HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "unknown-workflow"},
                "workspace": {"root": str(tmp_path)},
                "geographic": {"source_mode": "synthetic"},
            },
            base_dir=tmp_path,
        )
