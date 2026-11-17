"""Loading a TOML project with its ``base_config`` chain, from files in a temporary folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.toml_io.loader import (
    config_base_dir,
    load_toml_with_base_config,
    merge_toml_layers,
    origins_of,
    read_toml,
    read_toml_chain,
    validate_toml,
)
from hydromodpy.core.toml_io.merge import BaseConfigConflict


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


@pytest.mark.parametrize(
    ("written", "error", "message"),
    [
        ("base_config = 3", TypeError, "base_config must be a path or a list of paths"),
        ("base_config = ['b.toml', 4]", TypeError, "base_config must be a path or a list"),
        ("base_config = ['b.toml', './b.toml']", ValueError, "names './b.toml' twice"),
    ],
)
def test_bad_base_config_refused(tmp_path: Path, written: str, error: type, message: str) -> None:
    _write(tmp_path / "b.toml", "")
    path = _write(tmp_path / "a.toml", written + "\n")
    with pytest.raises(error, match=message):
        read_toml_chain(path, root=None)


def _diamond(tmp_path: Path, site: str = "", experiment: str = "") -> Path:
    """A run that inherits a site and an experiment, both on one model, outside a project."""
    _write(tmp_path / "model.toml", "[flow]\nK = 1.0\nSy = 0.1\n")
    _write(tmp_path / "sites" / "nancon.toml", 'base_config = "../model.toml"\n' + site)
    _write(tmp_path / "experiments" / "steady.toml", 'base_config = "../model.toml"\n' + experiment)
    return _write(
        tmp_path / "run.toml",
        'base_config = ["sites/nancon.toml", "experiments/steady.toml"]\n',
    )


def test_a_list_of_bases_is_read_as_a_graph_each_file_once(tmp_path: Path) -> None:
    run = _diamond(tmp_path, site="[site]\nname = 'nancon'\n", experiment="[flow]\nK = 5.0\n")

    chain = read_toml_chain(run, root=None)

    assert [item.path.relative_to(tmp_path).as_posix() for item in chain] == [
        "model.toml", "sites/nancon.toml", "experiments/steady.toml", "run.toml"
    ]  # fmt: skip
    assert chain[-1].bases == (chain[1].path, chain[2].path)
    assert load_toml_with_base_config(run, root=None) == {
        "flow": {"K": 5.0, "Sy": 0.1}, "site": {"name": "nancon"}
    }  # fmt: skip
    assert origins_of(chain)["flow.K"] == (chain[2].path,)
    # Outside a project, paths are read from the root reached by the first bases.
    assert config_base_dir(run, chain=chain) == tmp_path.resolve()


def test_two_bases_that_disagree_are_named_from_the_file_read(tmp_path: Path) -> None:
    run = _diamond(tmp_path, site="[flow]\nK = 3.0\n", experiment="[flow]\nK = 5.0\n")

    with pytest.raises(BaseConfigConflict, match="sites/nancon.toml .3.0. and by experiments"):
        load_toml_with_base_config(run, root=None)


def test_a_cycle_through_a_list_of_bases_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / "a.toml", 'base_config = ["b.toml"]\n')
    _write(tmp_path / "b.toml", 'base_config = ["c.toml", "a.toml"]\n')
    _write(tmp_path / "c.toml", "")

    with pytest.raises(ValueError, match="circular base_config chain: .*a.toml -> .*b.toml -> "):
        read_toml_chain(tmp_path / "a.toml", root=None)


def test_an_overlay_and_its_base_still_override_the_file(tmp_path: Path) -> None:
    main = read_toml_chain(_write(tmp_path / "main.toml", "x = 'file'\ny = 'file'\n"), root=None)
    _write(tmp_path / "shared.toml", "x = 'shared'\n")
    overlay = read_toml_chain(
        _write(tmp_path / "o.toml", 'base_config = "shared.toml"\ny = ""\n'), root=None
    )

    # The empty string of an overlay is dropped and never removes the value of the file.
    assert merge_toml_layers([main, overlay], root=None) == {"x": "shared", "y": "file"}


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
