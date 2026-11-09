"""Loading a TOML project with its ``base_config`` chain, from files in a temporary folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.toml_io.loader import (
    ChainFile,
    config_base_dir,
    load_toml_with_base_config,
    merge_toml_chain,
    merge_toml_layers,
    read_toml,
    read_toml_chain,
    validate_toml,
)


class _Doc(BaseModel):
    """A minimal chain document the migrations act on."""

    legacy: str | None = None
    current: str | None = None


def _no_root() -> RootConfig | None:
    return None


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


def test_a_file_is_read_even_with_a_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "a.toml"
    path.write_bytes(b"\xef\xbb\xbfx = 1\n")
    assert read_toml(path) == {"x": 1}


def test_a_windows_path_in_a_basic_string_is_repaired(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", 'dem_path = "C:\\data\\dem.tif"\nname = "x"\n')
    assert read_toml(path) == {"dem_path": "C:\\data\\dem.tif", "name": "x"}


def test_a_syntax_error_that_is_not_a_path_is_raised(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", 'name = "a\\qb"\n')
    with pytest.raises(Exception, match="escape|Invalid"):
        read_toml(path)


def test_the_child_overrides_the_base_and_keeps_what_it_does_not_write(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", "[flow]\nk = 1.0\nss = 0.1\n")
    child = _write(tmp_path / "child.toml", 'base_config = "base.toml"\n[flow]\nk = 2.0\n')
    assert load_toml_with_base_config(child, root=None) == {"flow": {"k": 2.0, "ss": 0.1}}


def test_root_none_reads_the_files_the_way_they_are_written(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", "legacy = 'base'\n")
    child = _write(tmp_path / "child.toml", 'base_config = "base.toml"\nlegacy = "child"\n')
    assert load_toml_with_base_config(child, root=None) == {"legacy": "child"}


def test_root_migrates_each_file_of_the_chain_and_the_merge(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", 'legacy = "base"\n')
    child = _write(tmp_path / "child.toml", 'base_config = "base.toml"\n')
    recorded: list[Any] = []
    root = _migrating_root(recorded)
    merged = load_toml_with_base_config(child, root=root)
    assert merged == {"current": "base"}
    sources = [source for entry in recorded if isinstance(entry, tuple) for source, _doc in [entry]]
    assert sources == [tmp_path / "base.toml", child]
    assert "merged" in recorded


def test_an_old_name_in_one_file_meets_a_new_name_in_another(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", 'legacy = "base"\n')
    child = _write(tmp_path / "child.toml", 'base_config = "base.toml"\ncurrent = "child"\n')
    recorded: list[Any] = []
    merged = load_toml_with_base_config(child, root=_migrating_root(recorded))
    assert merged == {"current": "child"}


def test_a_chain_is_read_root_first_without_the_base_config_key(tmp_path: Path) -> None:
    _write(tmp_path / "a.toml", "x = 1\n")
    _write(tmp_path / "b.toml", 'base_config = "a.toml"\ny = 2\n')
    c = _write(tmp_path / "sub" / "c.toml", 'base_config = "../b.toml"\nz = 3\n')
    chain = read_toml_chain(c, root=None)
    assert [item.path.name for item in chain] == ["a.toml", "b.toml", "c.toml"]
    assert all(isinstance(item, ChainFile) for item in chain)
    assert [item.own for item in chain] == [{"x": 1}, {"y": 2}, {"z": 3}]


def test_a_circular_chain_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / "a.toml", 'base_config = "b.toml"\n')
    a = _write(tmp_path / "b.toml", 'base_config = "a.toml"\n')
    with pytest.raises(ValueError, match="circular base_config chain"):
        read_toml_chain(a, root=None)


def test_a_base_config_that_is_not_a_string_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", "base_config = 3\n")
    with pytest.raises(TypeError, match="base_config must be a TOML string"):
        read_toml_chain(path, root=None)


def test_an_empty_base_config_means_no_base(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", 'base_config = ""\nx = 1\n')
    assert load_toml_with_base_config(path, root=None) == {"x": 1}


def test_an_absolute_base_config_is_followed(tmp_path: Path) -> None:
    base = _write(tmp_path / "elsewhere" / "base.toml", "x = 1\n")
    child = _write(tmp_path / "child.toml", f'base_config = "{base.as_posix()}"\ny = 2\n')
    assert load_toml_with_base_config(child, root=None) == {"x": 1, "y": 2}


def test_an_empty_string_placeholder_falls_back_to_the_base_value(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", 'mask = "m.tif"\nkeep = "k"\n')
    child = _write(
        tmp_path / "child.toml",
        'base_config = "base.toml"\nname = ""\nitems = [{a = "", b = 1}, 5]\n[t]\nz = ""\n',
    )
    merged = load_toml_with_base_config(child, root=None)
    assert merged == {"mask": "m.tif", "keep": "k", "items": [{"b": 1}, 5], "t": {}}


def test_overlays_cli_and_env_win_in_that_order(tmp_path: Path) -> None:
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


def test_overlays_and_sourced_overrides_are_migrated(tmp_path: Path) -> None:
    from hydromodpy.core.toml_io.overrides import ENV_SOURCE, SET_SOURCE

    main = read_toml_chain(_write(tmp_path / "main.toml", ""), root=None)
    overlay = read_toml_chain(_write(tmp_path / "o.toml", ""), root=None)
    recorded: list[Any] = []
    merged = merge_toml_layers(
        [main, overlay],
        root=_migrating_root(recorded),
        cli_overrides={"legacy": "cli"},
        env_overrides={},
    )
    assert merged == {"current": "cli"}
    sources = [entry[0] for entry in recorded if isinstance(entry, tuple)]
    assert sources == [tmp_path / "main.toml", tmp_path / "o.toml", SET_SOURCE]
    assert ENV_SOURCE  # the env payload reaches the layers only when it holds keys


def test_merge_chain_without_root_gives_the_same_document(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", "x = 1\n")
    files = read_toml_chain(path, root=None)
    assert merge_toml_chain(files, root=None) == {"x": 1}


def test_the_project_root_is_the_folder_with_project_toml(tmp_path: Path) -> None:
    _write(tmp_path / "project.toml", "x = 1\n")
    nested = _write(tmp_path / "plan" / "case.toml", "y = 1\n")
    assert config_base_dir(nested) == tmp_path.resolve()


def test_outside_a_project_the_root_file_of_the_chain_gives_the_base_dir(tmp_path: Path) -> None:
    _write(tmp_path / "shared" / "base.toml", "x = 1\n")
    child = _write(tmp_path / "work" / "case.toml", 'base_config = "../shared/base.toml"\n')
    assert config_base_dir(child) == (tmp_path / "shared").resolve()


def test_a_file_alone_is_its_own_base_dir(tmp_path: Path) -> None:
    path = _write(tmp_path / "case.toml", "x = 1\n")
    assert config_base_dir(path) == tmp_path.resolve()


def test_a_chain_already_read_gives_the_base_dir_without_a_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "shared" / "base.toml", "x = 1\n")
    child = _write(tmp_path / "work" / "case.toml", 'base_config = "../shared/base.toml"\n')
    chain = read_toml_chain(child, root=None)

    def no_read(path: Path) -> dict[str, Any]:
        raise AssertionError(f"{path} read again")

    monkeypatch.setattr("hydromodpy.core.toml_io.loader.read_toml", no_read)
    assert config_base_dir(child, chain=chain) == (tmp_path / "shared").resolve()


class _Flow(BaseModel):
    k: float = 1.0


class _Model(BaseModel):
    flow: _Flow = _Flow()


def test_validate_toml_builds_the_model_from_the_chain(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", "[flow]\nk = 4.0\n")
    child = _write(tmp_path / "c.toml", 'base_config = "base.toml"\n')
    assert validate_toml(_Model, child, root=None).flow.k == 4.0


def test_validate_toml_migrates_through_the_root(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.toml", 'legacy = "x"\n')
    assert validate_toml(_Doc, path, root=_migrating_root([])).current == "x"


@pytest.mark.parametrize(
    ("section", "expected"),
    [("flow", 4.0), ("absent.deeper", 1.0), ("flow.k", 1.0)],
)
def test_validate_toml_reads_a_section_and_falls_back_to_defaults(
    tmp_path: Path, section: str, expected: float
) -> None:
    path = _write(tmp_path / "c.toml", "[flow]\nk = 4.0\n")
    model = _Flow if section == "flow" else _Model
    result = validate_toml(model, path, root=None, section=section)
    assert (result.k if model is _Flow else result.flow.k) == expected


def test_validate_toml_lets_the_resolver_replace_the_model_with_the_project_root(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "project.toml", "")
    path = _write(tmp_path / "sub" / "c.toml", "[flow]\nk = 2.0\n")
    seen: list[Path] = []

    def resolver(cfg: _Model, base: Path) -> _Model | None:
        seen.append(base)
        return _Model(flow=_Flow(k=9.0))

    assert validate_toml(_Model, path, root=None, base_dir_resolver=resolver).flow.k == 9.0
    assert seen == [tmp_path.resolve()]
    assert validate_toml(_Model, path, root=None, base_dir_resolver=lambda c, b: None).flow.k == 2.0
