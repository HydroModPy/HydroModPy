"""The one loader of a configuration and the one reader of a TOML file, in tables.

A TOML file, a mapping, JSON text and a built configuration load into the same
configuration from the same base. A file reads its chain once. A document in
memory needs its base. Every refusal is a row of ``REFUSALS``, with its type, its
exit code by the mapper of the CLI and a fragment of its sentence.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, exit_code_for
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.config.loading import (
    MEMORY_NEEDS_BASE,
    ConfigFileError,
    load,
    read_document,
)
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, forget_old_forms_told
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError

DOCUMENT: dict[str, Any] = {
    "workflow": {"mode": "simulation"},
    "site": {"name": "site_a"},
    "geographic": {"catchment": {"kind": "dem"}},
    "data": {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}},
    "simulation": {"name": "island"},
}
OLD_TABLE = {"modflow6": {"process_specific": {"vka": 2.0}}}


@pytest.fixture(autouse=True)
def _told_again() -> None:
    """A warning is told once per file and key, so each test starts from none told."""
    forget_old_forms_told()


def _project(root: Path, document: dict[str, Any] = DOCUMENT) -> Path:
    """Write a project with *document* as ``island.toml`` and its DEM, and return the root."""
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "inputs" / "dem.tif").write_bytes(b"never read")
    (root / "project.toml").write_text("[workspace]\n", encoding="utf-8")
    (root / "island.toml").write_text(tomlkit.dumps(document), encoding="utf-8")
    return root


def _object(root: Path) -> HydroModPyConfig:
    return load(root / "island.toml")


FORMS: dict[str, Callable[[Path], tuple[Any, Any]]] = {
    "toml file": lambda root: (root / "island.toml", None),
    "toml text path": lambda root: (str(root / "island.toml"), None),
    "dict": lambda root: (DOCUMENT, root),
    "json text": lambda root: (json.dumps(DOCUMENT), root),
    "object": lambda root: (_object(root), None),
}


@pytest.mark.parametrize("form", sorted(FORMS))
def test_every_form_gives_the_same_configuration_and_base(tmp_path: Path, form: str) -> None:
    root = _project(tmp_path / "project")
    expected = written_payload(load(root / "island.toml"))
    source, base = FORMS[form](root)

    cfg = load(source, base)

    assert written_payload(cfg) == expected
    assert cfg.workspace.project_root == root.resolve()
    assert cfg.data.dem.sources[0].path == (root / "inputs" / "dem.tif").resolve()


def test_a_relative_path_of_a_dict_is_read_from_the_base(tmp_path: Path) -> None:
    root = _project(tmp_path / "elsewhere")

    cfg = load(DOCUMENT, root)

    assert cfg.data.dem.sources[0].path == root.resolve() / "inputs" / "dem.tif"


def test_a_base_given_wins_over_the_folder_of_the_file(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    other = _project(tmp_path / "other")

    cfg = load(root / "island.toml", other)

    assert cfg.workspace.project_root == other.resolve()
    assert cfg.data.dem.sources[0].path == other.resolve() / "inputs" / "dem.tif"


def test_a_file_outside_a_project_reads_from_the_root_of_its_chain(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "inputs").mkdir()
    (shared / "inputs" / "dem.tif").write_bytes(b"x")
    (shared / "base.toml").write_text(tomlkit.dumps(DOCUMENT), encoding="utf-8")
    child = tmp_path / "work" / "case.toml"
    child.parent.mkdir()
    child.write_text('base_config = "../shared/base.toml"\n', encoding="utf-8")

    cfg = load(child)

    assert cfg.workspace.project_root == shared.resolve()


@pytest.mark.parametrize(
    ("document", "named"),
    [
        pytest.param(
            {k: v for k, v in DOCUMENT.items() if k != "simulation"}, "case_a", id="from the file"
        ),
        pytest.param(DOCUMENT, "island", id="as written"),
    ],
)
def test_a_mapping_read_from_a_file_is_named_like_the_file(
    tmp_path: Path, document: dict[str, Any], named: str
) -> None:
    """A name made from the file is folded: ``run_`` dropped, then lower case."""
    root = _project(tmp_path / "project")

    cfg = load(document, root, source_path=root / "run_Case A.toml")

    assert cfg.simulation.name == named


def test_the_changes_are_applied_once_on_top_of_a_mapping(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")

    cfg = load(DOCUMENT, root, changes={"simulation.name": "changed"})

    assert cfg.simulation.name == "changed"
    assert DOCUMENT["simulation"]["name"] == "island"


def test_an_object_takes_its_changes_and_stays_itself_without(tmp_path: Path) -> None:
    cfg = _object(_project(tmp_path / "project"))

    assert load(cfg) is cfg
    assert load(cfg, changes={"simulation.name": "other"}).simulation.name == "other"


# The layers of a file: the chain, the overlays, then the changes, each read once.


def test_the_layers_merge_in_the_order_of_the_command_line(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[a]\nx = 1\ny = 1\nz = 1\nw = 1\n", encoding="utf-8")
    (tmp_path / "main.toml").write_text(
        'base_config = "base.toml"\n[a]\ny = 2\nz = 2\nw = 2\n', encoding="utf-8"
    )
    (tmp_path / "over.toml").write_text("[a]\nz = 3\nw = 3\n", encoding="utf-8")

    document = read_document(
        tmp_path / "main.toml", overlays=[tmp_path / "over.toml"], changes={"a.w": 4}, root=None
    )

    assert document == {"a": {"x": 1, "y": 2, "z": 3, "w": 4}}


def test_a_load_reads_each_file_of_the_chain_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy.core.toml_io.loader as loader

    root = tmp_path / "flat"
    root.mkdir()
    (root / "inputs").mkdir()
    (root / "inputs" / "dem.tif").write_bytes(b"x")
    (root / "base.toml").write_text(tomlkit.dumps(DOCUMENT), encoding="utf-8")
    (root / "case.toml").write_text(
        'base_config = "base.toml"\n[simulation]\nname = "case"\n', encoding="utf-8"
    )
    reads: list[Path] = []
    real = loader.read_toml

    def counted(path: Path) -> dict[str, Any]:
        reads.append(Path(path))
        return real(path)

    monkeypatch.setattr(loader, "read_toml", counted)

    cfg = load(root / "case.toml")

    assert cfg.simulation.name == "case"
    assert sorted(path.name for path in reads) == ["base.toml", "case.toml"]


@pytest.mark.parametrize("form", ["toml file", "dict", "json text"])
def test_an_old_form_is_migrated_in_every_form(tmp_path: Path, form: str) -> None:
    document = {**DOCUMENT, **OLD_TABLE}
    root = _project(tmp_path / "project", document)
    source, base = {
        "toml file": (root / "island.toml", None),
        "dict": (document, root),
        "json text": (json.dumps(document), root),
    }[form]

    with pytest.warns(ConfigKeyRenamedWarning, match=r"modflow6 -> \[solver\.modflow6\]"):
        cfg = load(source, base)

    assert cfg.solver.options_of("modflow6").process_specific.vka == 2.0


def test_a_set_under_an_old_name_is_told_under_set(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")

    with pytest.warns(ConfigKeyRenamedWarning, match="--set"):
        cfg = load(DOCUMENT, root, changes={"modflow6.process_specific.vka": 5.0})

    assert cfg.solver.options_of("modflow6").process_specific.vka == 5.0


def test_from_toml_dict_and_json_are_the_loader(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    expected = written_payload(load(DOCUMENT, root))

    assert written_payload(HydroModPyConfig.from_dict(DOCUMENT, base_dir=root)) == expected
    assert written_payload(HydroModPyConfig.from_json(json.dumps(DOCUMENT), base_dir=root)) == (
        expected
    )
    assert HydroModPyConfig.from_toml(root / "island.toml").simulation.name == "island"


# Every refusal, with its type, its exit code by the mapper and a fragment of its sentence.


def _refused_by(root: Path, row: str) -> Callable[[], Any]:
    with_root = {**DOCUMENT, "workspace": {"project_root": str(root)}}
    with_chain = {**DOCUMENT, "base_config": "base.toml"}
    (root / "notes.txt").write_text("x", encoding="utf-8")
    (root / "script.py").write_text("x = 1\n", encoding="utf-8")
    (root / "request.json").write_text("{}", encoding="utf-8")
    (root / "broken.toml").write_text("[a\n", encoding="utf-8")
    (root / "over.json").write_text("{}", encoding="utf-8")
    return {
        "dict without base": lambda: load(DOCUMENT),
        "json text without base": lambda: load(json.dumps(DOCUMENT)),
        "project_root in a dict": lambda: load(with_root, root),
        "project_root in a file": lambda: load(_with_file(root, with_root)),
        "base_config in a dict": lambda: load(with_chain, root),
        "json text that does not parse": lambda: load("{not json", root),
        "json text that is no object": lambda: HydroModPyConfig.from_json("[1, 2]", base_dir=root),
        "a python script": lambda: load(root / "script.py"),
        "an unknown suffix": lambda: load(root / "notes.txt"),
        "a run request given to the loader": lambda: load(root / "request.json"),
        "a toml file that does not parse": lambda: load(root / "broken.toml"),
        "a json overlay": lambda: read_document(
            root / "island.toml", overlays=[root / "over.json"], root=ROOT_CONFIG
        ),
        "a missing file": lambda: load(root / "absent.toml"),
        "from_dict without base": lambda: HydroModPyConfig.from_dict(DOCUMENT),  # type: ignore[call-arg]
    }[row]


def _with_file(root: Path, document: dict[str, Any]) -> Path:
    path = root / "rooted.toml"
    path.write_text(tomlkit.dumps(document), encoding="utf-8")
    return path


REFUSALS: list[tuple[str, type[BaseException], int | None, str]] = [
    ("dict without base", ConfigError, EXIT_CONFIG, MEMORY_NEEDS_BASE),
    ("json text without base", ConfigError, EXIT_CONFIG, "needs base="),
    ("project_root in a dict", ConfigValidationError, EXIT_CONFIG, "project_root is not a key"),
    ("project_root in a file", ConfigValidationError, EXIT_CONFIG, "project_root is not a key"),
    ("base_config in a dict", ConfigError, EXIT_CONFIG, "base_config is a key of a TOML file"),
    ("json text that does not parse", ConfigError, EXIT_CONFIG, "is not valid JSON"),
    ("json text that is no object", ConfigValidationError, EXIT_CONFIG, "table of sections"),
    ("a python script", ConfigError, EXIT_CONFIG, "Python scripts are not supported"),
    ("an unknown suffix", ConfigError, EXIT_CONFIG, "Unsupported file type: .txt"),
    ("a run request given to the loader", ConfigError, EXIT_CONFIG, "is a run request"),
    ("a toml file that does not parse", ConfigFileError, EXIT_CONFIG, "Invalid TOML in"),
    ("a json overlay", ConfigError, EXIT_CONFIG, "over.json is not a TOML file"),
    ("a missing file", FileNotFoundError, EXIT_NOT_FOUND, "absent.toml"),
    ("from_dict without base", TypeError, None, "base_dir"),
]


@pytest.mark.parametrize(
    ("row", "kind", "code", "said"), REFUSALS, ids=[row[0] for row in REFUSALS]
)
def test_a_refusal_has_its_type_its_code_and_its_sentence(
    tmp_path: Path, row: str, kind: type[BaseException], code: int | None, said: str
) -> None:
    root = _project(tmp_path / "project")

    with pytest.raises(kind) as refused:
        _refused_by(root, row)()

    assert said in str(refused.value)
    if code is not None:
        assert exit_code_for(refused.value) == code
