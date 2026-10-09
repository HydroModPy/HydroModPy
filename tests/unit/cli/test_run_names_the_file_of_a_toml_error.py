"""``hmp run`` names the file and the cause of a TOML error, not an override."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands.run import _ConfigFileError, _materialize_effective_toml


def _args(set_overrides: list[str] | None = None) -> argparse.Namespace:
    return argparse.Namespace(overlay=[], set_overrides=set_overrides or [])


def test_a_syntax_error_in_a_base_file_names_that_file(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[workflow\nmode = 'simulation'\n", encoding="utf-8")
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n', encoding="utf-8")

    with pytest.raises(_ConfigFileError, match=r"Invalid TOML in .*base\.toml: Expected"):
        _materialize_effective_toml(child, args=_args())


def test_a_circular_chain_is_a_file_error(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('base_config = "b.toml"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n', encoding="utf-8")

    with pytest.raises(_ConfigFileError, match="circular base_config chain"):
        _materialize_effective_toml(tmp_path / "a.toml", args=_args())


def test_a_bad_set_item_is_still_an_override_error(tmp_path: Path) -> None:
    config = tmp_path / "ok.toml"
    config.write_text("[workflow]\nmode = 'simulation'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="--set expects PATH=VALUE") as caught:
        _materialize_effective_toml(config, args=_args(set_overrides=["foo"]))
    assert not isinstance(caught.value, _ConfigFileError)
