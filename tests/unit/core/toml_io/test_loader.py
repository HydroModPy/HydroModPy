"""Loading a TOML project with its ``base_config`` chain, from files in a temporary folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.toml_io.loader import (
    merge_toml_layers,
    read_toml,
    read_toml_chain,
    validate_toml,
)


class _Doc(BaseModel):
    """A minimal chain document the migrations act on."""

    legacy: str | None = None
    current: str | None = None


def _migrating_root(recorded: list[Any]) -> RootConfig:
    """A root whose rules rename ``legacy`` to ``current`` and record their layers."""

    def migrate_layers(layers: Any) -> list[str]:
        recorded.extend(layers)
        changed: list[str] = []
        for _source, doc in layers:
            if document_says_legacy(doc):
                doc["current"] = doc.pop("legacy")
                changed.append("current (renamed from legacy)")
        return changed

    def migrate_merged(document: Any, layers: Any) -> list[str]:
        recorded.append("merged")
        if document_says_legacy(document):
            document["current"] = document.pop("legacy")
            return ["current (renamed from legacy)"]
        return []

    return RootConfig(model=_Doc, migrate_layers=migrate_layers, migrate_merged=migrate_merged)


def document_says_legacy(doc: Any) -> bool:
    """Whether *doc* writes ``legacy`` and nothing has renamed it yet."""
    return isinstance(doc, dict) and doc.get("legacy") is not None and "current" not in doc


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_windows_path_is_repaired(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", 'dem_path = "C:\\data\\dem.tif"\nname = "x"\n')
    assert read_toml(path) == {"dem_path": "C:\\data\\dem.tif", "name": "x"}


def test_a_real_syntax_error_is_raised(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", 'name = "a\\qb"\n')
    with pytest.raises(Exception, match="escape|Invalid"):
        read_toml(path)


def test_bad_base_config_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", "base_config = 3\n")
    with pytest.raises(TypeError, match="base_config must be a TOML string"):
        read_toml_chain(path, root=None)


def test_overlay_cli_env_order(tmp_path: Path) -> None:
    main = read_toml_chain(
        _write(tmp_path / "main.toml", "x = 'file'\ny = 'file'\nz = 'file'\n"), root=None
    )
    overlay = read_toml_chain(
        _write(tmp_path / "o.toml", "x = 'overlay'\ny = 'overlay'\n"), root=None
    )
    merged = merge_toml_layers(
        [main, overlay],
        root=None,
        cli_overrides={"y": "cli", "w": "cli"},
        env_overrides={"w": "env"},
    )
    assert merged == {"x": "overlay", "y": "cli", "z": "file", "w": "env"}


class _Flow(BaseModel):
    k: float = 1.0


class _Model(BaseModel):
    flow: _Flow = _Flow()


def test_validate_toml_migrates(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.toml", 'legacy = "x"\n')
    assert validate_toml(_Doc, path, root=_migrating_root([])).current == "x"


def test_validate_toml_reads_a_section(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.toml", "[flow]\nk = 4.0\n")
    assert validate_toml(_Flow, path, root=None, section="flow").k == 4.0


@pytest.mark.parametrize("section", ["absent.deeper", "flow.k"])
def test_validate_toml_falls_back_to_defaults(tmp_path: Path, section: str) -> None:
    path = _write(tmp_path / "c.toml", "[flow]\nk = 4.0\n")
    assert validate_toml(_Model, path, root=None, section=section).flow.k == 1.0


def test_the_resolver_may_replace_the_model(tmp_path: Path) -> None:
    _write(tmp_path / "project.toml", "")
    path = _write(tmp_path / "sub" / "c.toml", "[flow]\nk = 2.0\n")
    seen: list[Path] = []

    def resolver(cfg: _Model, base: Path) -> _Model | None:
        seen.append(base)
        return _Model(flow=_Flow(k=9.0))

    assert validate_toml(_Model, path, root=None, base_dir_resolver=resolver).flow.k == 9.0
    assert seen == [tmp_path.resolve()]
    assert validate_toml(_Model, path, root=None, base_dir_resolver=lambda c, b: None).flow.k == 2.0
