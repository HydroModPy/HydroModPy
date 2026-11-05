"""Loading a TOML project with its ``base_config`` chain, from files in a temporary folder."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from hydromodpy.core.toml_io import loader
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


class _NoMigration:
    """A root-config provider that leaves every layer as written."""

    def migrate_layers(self, layers):
        return []

    def migrate_merged(self, document, layers):
        return []


@pytest.fixture(autouse=True)
def _no_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "get_root_config_provider", lambda: _NoMigration())
    monkeypatch.delenv("HMP_PROJECT_ROOT", raising=False)


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
    assert load_toml_with_base_config(child) == {"flow": {"k": 2.0, "ss": 0.1}}


def test_a_chain_is_read_root_first_without_the_base_config_key(tmp_path: Path) -> None:
    _write(tmp_path / "a.toml", "x = 1\n")
    _write(tmp_path / "b.toml", 'base_config = "a.toml"\ny = 2\n')
    c = _write(tmp_path / "sub" / "c.toml", 'base_config = "../b.toml"\nz = 3\n')
    chain = read_toml_chain(c)
    assert [item.path.name for item in chain] == ["a.toml", "b.toml", "c.toml"]
    assert all(isinstance(item, ChainFile) for item in chain)
    assert [item.own for item in chain] == [{"x": 1}, {"y": 2}, {"z": 3}]


def test_a_circular_chain_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / "a.toml", 'base_config = "b.toml"\n')
    a = _write(tmp_path / "b.toml", 'base_config = "a.toml"\n')
    with pytest.raises(ValueError, match="circular base_config chain"):
        read_toml_chain(a)


def test_a_base_config_that_is_not_a_string_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", "base_config = 3\n")
    with pytest.raises(TypeError, match="base_config must be a TOML string"):
        read_toml_chain(path)


def test_an_empty_base_config_means_no_base(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", 'base_config = ""\nx = 1\n')
    assert load_toml_with_base_config(path) == {"x": 1}


def test_an_absolute_base_config_is_followed(tmp_path: Path) -> None:
    base = _write(tmp_path / "elsewhere" / "base.toml", "x = 1\n")
    child = _write(tmp_path / "child.toml", f'base_config = "{base.as_posix()}"\ny = 2\n')
    assert load_toml_with_base_config(child) == {"x": 1, "y": 2}


def test_an_empty_string_placeholder_falls_back_to_the_base_value(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", 'mask = "m.tif"\nkeep = "k"\n')
    child = _write(
        tmp_path / "child.toml",
        'base_config = "base.toml"\nname = ""\nitems = [{a = "", b = 1}, 5]\n[t]\nz = ""\n',
    )
    merged = load_toml_with_base_config(child)
    assert merged == {"mask": "m.tif", "keep": "k", "items": [{"b": 1}, 5], "t": {}}


def test_overlays_cli_and_env_win_in_that_order(tmp_path: Path) -> None:
    main = read_toml_chain(_write(tmp_path / "main.toml", "x = 'file'\ny = 'file'\nz = 'file'\n"))
    overlay = read_toml_chain(_write(tmp_path / "o.toml", "x = 'overlay'\ny = 'overlay'\n"))
    merged = merge_toml_layers(
        [main, overlay], cli_overrides={"y": "cli", "w": "cli"}, env_overrides={"w": "env"}
    )
    assert merged == {"x": "overlay", "y": "cli", "z": "file", "w": "env"}


def test_merge_chain_without_migration_gives_the_same_document(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.toml", "x = 1\n")
    files = read_toml_chain(path, migrate=False)
    assert merge_toml_chain(files, migrate=False) == merge_toml_chain(files) == {"x": 1}


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


class _Flow(BaseModel):
    k: float = 1.0


class _Doc(BaseModel):
    flow: _Flow = _Flow()


def test_validate_toml_builds_the_model_from_the_chain(tmp_path: Path) -> None:
    _write(tmp_path / "base.toml", "[flow]\nk = 4.0\n")
    child = _write(tmp_path / "c.toml", 'base_config = "base.toml"\n')
    assert validate_toml(_Doc, child).flow.k == 4.0


@pytest.mark.parametrize(
    ("section", "expected"),
    [("flow", 4.0), ("absent.deeper", 1.0), ("flow.k", 1.0)],
)
def test_validate_toml_reads_a_section_and_falls_back_to_defaults(
    tmp_path: Path, section: str, expected: float
) -> None:
    path = _write(tmp_path / "c.toml", "[flow]\nk = 4.0\n")
    model = _Flow if section == "flow" else _Doc
    result = validate_toml(model, path, section=section)
    assert (result.k if model is _Flow else result.flow.k) == expected


def test_validate_toml_lets_the_resolver_replace_the_model_with_the_project_root(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "project.toml", "")
    path = _write(tmp_path / "sub" / "c.toml", "[flow]\nk = 2.0\n")
    seen: list[Path] = []

    def resolver(cfg: _Doc, base: Path) -> _Doc | None:
        seen.append(base)
        return _Doc(flow=_Flow(k=9.0))

    assert validate_toml(_Doc, path, base_dir_resolver=resolver).flow.k == 9.0
    assert seen == [tmp_path.resolve()]
    assert validate_toml(_Doc, path, base_dir_resolver=lambda c, b: None).flow.k == 2.0
