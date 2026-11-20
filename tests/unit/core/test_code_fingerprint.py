"""The fingerprint of the code that computes: what moves it and what does not.

It decides whether a run is the same computation as another one, so an edit of a
docstring must leave it alone and an edit of a solver must not. The trees are
written here, so an edit is a line of the test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tokenize
import tomllib
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path

import pytest

from hydromodpy.core import code_fingerprint as fingerprint_module
from hydromodpy.core.code_fingerprint import (
    COMPUTE_DATA_FILES,
    COMPUTE_LAYERS,
    LAYER_READS,
    OTHER_DATA_SUFFIXES,
    OUTSIDE_LAYERS,
    OUTSIDE_SUBTREES,
    RUN_LAYERS,
    clear_fingerprint_cache,
    code_fingerprint,
    fingerprint_tree,
    layers_under,
    normalised_source,
)
from hydromodpy.core.exceptions import HydroModPyError
from tools.doc_contracts import layer_rows, load_layer_matrix, present_layers

REPO_ROOT = Path(__file__).resolve().parents[3]

SOLVER = '''"""Module docstring."""

import math


def rate(x, y):
    """Say what it does."""
    # A comment.
    return math.sqrt(x) + f"{y:>{x}}"
'''


@pytest.fixture(autouse=True)
def _private_disk_cache(tmp_path_factory, monkeypatch) -> None:
    cache = tmp_path_factory.mktemp("fingerprint") / "fingerprint.json"
    monkeypatch.setattr(fingerprint_module, "_disk_cache_path", lambda: cache)
    clear_fingerprint_cache()


def _tree(root: Path) -> Path:
    for relative, text in {
        **{f"{layer}/__init__.py": "" for layer in COMPUTE_LAYERS},
        "solver/rate.py": SOLVER,
        "display/figure.py": "def draw():\n    return 1\n",
        "cli/main.py": "def main():\n    return 1\n",
        "results/storage/store.py": "VALUE = 1\n",
        "results/export/publish.py": "VALUE = 1\n",
        **{relative: "a,b\n" for relative in COMPUTE_DATA_FILES},
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _table(root: Path) -> dict[str, str]:
    clear_fingerprint_cache()
    return fingerprint_tree(root, RUN_LAYERS)


@pytest.mark.parametrize(
    "edited",
    [
        pytest.param(SOLVER.replace("Say what it does.", "Say it otherwise."), id="docstring"),
        pytest.param(SOLVER.replace("Module docstring.", "Another."), id="module-docstring"),
        pytest.param(SOLVER.replace("# A comment.", "# Another one."), id="comment"),
        pytest.param(SOLVER.replace("    # A comment.\n", ""), id="comment-gone"),
        pytest.param(SOLVER.replace("(x, y)", "(\n    x,\n    y\n)"), id="wrapped-call"),
        pytest.param(SOLVER.replace("import math\n", "import math  \n\n\n"), id="blank-lines"),
    ],
)
def test_edit_without_effect_moves_nothing(edited: str) -> None:
    assert normalised_source(edited) == normalised_source(SOLVER)


@pytest.mark.parametrize(
    ("edited", "word"),
    [
        pytest.param(SOLVER.replace("sqrt", "floor"), "name", id="call"),
        pytest.param(SOLVER.replace("{y:>{x}}", "{y:<{x}}"), "f-string", id="f-string"),
        pytest.param(SOLVER.replace("    return", "    if x:\n        return"), "if", id="branch"),
    ],
)
def test_edit_of_code_moves_digest(edited: str, word: str) -> None:
    assert normalised_source(edited) != normalised_source(SOLVER), word


def test_block_structure_is_digested() -> None:
    inside = "if a:\n    b()\n    c()\n"
    after = "if a:\n    b()\nc()\n"
    assert normalised_source(inside) != normalised_source(after)


def test_assigned_string_is_code() -> None:
    assert normalised_source('x = 1\n"""A note."""\n') == normalised_source("x = 1\n")
    assert normalised_source('x = "A note."\n') != normalised_source("x = 1\n")


@pytest.mark.parametrize(
    "fstring",
    ['f"{x:>{w}}"', 'f"{{literal}} {x!r}"', 'rf"a{x}\\d"', 'f"é{x}é"', 'f"""{x}\n{y}"""'],
)
def test_f_string_is_one_token(fstring: str) -> None:
    """Python 3.12 splits it in parts. The digest has to be the one 3.11 reads."""
    assert normalised_source(f"é = {fstring}\n") == f"é\n=\n{fstring}\nNEWLINE"
    assert tokenize.STRING in {
        kind for kind, _text in fingerprint_module._merged_tokens(f"a = {fstring}\n")
    }


def test_one_digest_per_layer(tmp_path: Path) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)
    assert set(base) == set(RUN_LAYERS)

    (root / "solver" / "rate.py").write_text(SOLVER.replace("sqrt", "floor"), encoding="utf-8")
    edited = _table(root)
    assert edited["solver"] != base["solver"]
    assert {k: v for k, v in edited.items() if k != "solver"} == {
        k: v for k, v in base.items() if k != "solver"
    }


@pytest.mark.parametrize(
    "outside",
    ["display/figure.py", "cli/main.py", "results/export/publish.py", "project/compare.py"],
)
def test_outside_edit_keeps_identity(tmp_path: Path, outside: str) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)

    path = root / outside
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def edited():\n    return 2\n", encoding="utf-8")

    assert _table(root) == base


def test_docstring_edit_keeps_identity(tmp_path: Path) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)

    (root / "solver" / "rate.py").write_text(
        SOLVER.replace("Say what it does.", "Another word."), encoding="utf-8"
    )

    assert _table(root) == base


@pytest.mark.parametrize(
    ("edited", "layer"),
    [("solver/added.py", "solver"), ("results/storage/added.py", "results")],
)
def test_new_module_moves_its_layer(tmp_path: Path, edited: str, layer: str) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)
    (root / edited).write_text("VALUE = 2\n", encoding="utf-8")
    assert _table(root)[layer] != base[layer]


def test_compute_data_enters_digest(tmp_path: Path) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)
    relative = COMPUTE_DATA_FILES[0]
    (root / relative).write_text("a,b\n1,2\n", encoding="utf-8")
    assert _table(root)[relative.split("/")[0]] != base[relative.split("/")[0]]


@pytest.mark.parametrize(
    ("removed", "named"),
    [
        pytest.param("config/__init__.py", "any Python source in config/", id="no-source"),
        pytest.param(COMPUTE_DATA_FILES[0], COMPUTE_DATA_FILES[0], id="no-listed-data"),
    ],
)
def test_broken_install_is_refused(tmp_path: Path, removed: str, named: str) -> None:
    """A layer without source would hash as the digest of nothing, like any other broken one."""
    root = _tree(tmp_path / "hydromodpy")
    (root / removed).unlink()
    with pytest.raises(HydroModPyError, match=named):
        _table(root)


def _packages_of(folder: Path) -> Iterator[Path]:
    """Yield the folders ``packages.find`` gives: a package, then what is a package below it."""
    if (folder / "__init__.py").is_file():
        yield folder
        for child in folder.iterdir():
            if child.is_dir():
                yield from _packages_of(child)


def _shipped_data() -> dict[str, list[str]]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["setuptools"]["package-data"]


@pytest.mark.parametrize("relative", COMPUTE_DATA_FILES)
def test_data_file_ships_in_wheel(relative: str) -> None:
    folder, name = f"hydromodpy/{relative}".rsplit("/", 1)
    patterns = _shipped_data().get(folder.replace("/", "."), ())
    assert any(fnmatch(name, pattern) for pattern in patterns), relative


def test_wheel_and_checkout_hash_alike(tmp_path: Path) -> None:
    """A wheel holds the modules of its packages and the declared data, and nothing else."""
    package = REPO_ROOT / "hydromodpy"
    wheel = tmp_path / "hydromodpy"
    shipped = _shipped_data()
    for folder in _packages_of(package):
        target = wheel / folder.relative_to(package)
        target.mkdir(parents=True, exist_ok=True)
        relative = folder.relative_to(REPO_ROOT).as_posix()
        for pattern in ("*.py", *shipped.get(relative.replace("/", "."), ())):
            for path in folder.glob(pattern):
                shutil.copy2(path, target / path.name)
    assert fingerprint_tree(wheel, COMPUTE_LAYERS) == fingerprint_tree(package, COMPUTE_LAYERS)


def test_table_is_cached(tmp_path: Path, monkeypatch) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)

    calls: list[str] = []
    monkeypatch.setattr(
        fingerprint_module,
        "normalised_source",
        lambda source: calls.append(source) or "never read",
    )
    assert fingerprint_tree(root, RUN_LAYERS) == base
    clear_fingerprint_cache()
    # A new process reads the disk: only a file whose bytes changed is tokenized.
    assert fingerprint_tree(root, RUN_LAYERS) == base
    assert calls == []


def test_bad_disk_cache_is_harmless(tmp_path: Path, monkeypatch) -> None:
    root = _tree(tmp_path / "hydromodpy")
    base = _table(root)

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(fingerprint_module, "_disk_cache_path", lambda: corrupt)
    assert _table(root) == base
    assert json.loads(corrupt.read_text(encoding="utf-8"))

    blocked = tmp_path / "file"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setattr(fingerprint_module, "_disk_cache_path", lambda: blocked / "cache.json")
    assert _table(root) == base


def test_outside_layer_is_refused() -> None:
    with pytest.raises(ValueError, match="not a compute layer: display"):
        code_fingerprint(("display",))


def test_scope_covers_layer_matrix() -> None:
    """A layer of the tree has to say whether it changes a number.

    The matrix names the layers that exist today, the packages that leave
    included and the packages to come left out, so a move updates both lists.
    """
    declared = present_layers(load_layer_matrix())
    assert set(COMPUTE_LAYERS) | set(OUTSIDE_LAYERS) == declared
    assert not set(COMPUTE_LAYERS) & set(OUTSIDE_LAYERS)
    assert {"display", "project", "cli"} <= set(OUTSIDE_LAYERS)
    assert set(RUN_LAYERS) == set(COMPUTE_LAYERS) - {"calibration"}


def test_layer_reads_follow_matrix() -> None:
    """The closure of each compute layer is its matrix row, outside layers dropped."""
    rows = layer_rows(load_layer_matrix()).target
    compute = set(COMPUTE_LAYERS)
    expected = {
        layer: tuple(target for target in rows[layer] if target in compute)
        for layer in COMPUTE_LAYERS
    }
    assert LAYER_READS == expected


def test_layers_under_closure() -> None:
    assert layers_under("mesh") == ("core", "catchment", "mesh")
    assert layers_under("model") == ("core", "catchment", "mesh", "model")


def test_layers_under_refusal() -> None:
    with pytest.raises(ValueError, match="not a compute layer: display"):
        layers_under("display")


def test_package_files_are_classified() -> None:
    """A table a computation could read has to say whether it enters the fingerprint."""
    package = REPO_ROOT / "hydromodpy"
    outside = tuple(f"{subtree}/" for subtree in OUTSIDE_SUBTREES)
    unknown = []
    for layer in COMPUTE_LAYERS:
        for path in (package / layer).rglob("*"):
            relative = path.relative_to(package).as_posix()
            if (
                path.is_dir()
                or "__pycache__" in path.parts
                or path.suffix in (*OTHER_DATA_SUFFIXES, ".py")
                or relative.startswith(outside)
                or relative in COMPUTE_DATA_FILES
            ):
                continue
            unknown.append(relative)
    assert unknown == []
    assert all((package / relative).is_file() for relative in COMPUTE_DATA_FILES)
    assert all((package / subtree).is_dir() for subtree in OUTSIDE_SUBTREES)


@pytest.mark.allow_subprocess
@pytest.mark.parametrize(
    "other",
    [
        Path.home() / ".cache" / "hmp-ci" / "venv311" / "bin" / "python3.11",
        *(Path(shutil.which(name) or name) for name in ("python3.11", "python3.12", "python3.13")),
    ],
    ids=str,
)
def test_python_versions_agree(other: Path, tmp_path: Path) -> None:
    """The module runs alone under any interpreter, since it imports the standard library."""
    if not other.is_file() or subprocess.run([str(other), "--version"]).returncode != 0:
        pytest.skip(f"no working interpreter at {other}")
    source = Path(fingerprint_module.__file__)
    script = (
        "import importlib.util, json, pathlib, sys\n"
        f"spec = importlib.util.spec_from_file_location('fp', {str(source)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['fp'] = module\n"
        "spec.loader.exec_module(module)\n"
        "print(json.dumps([\n"
        "    module.normalised_source(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "]))\n"
    )
    probe = tmp_path / "probe.py"
    probe.write_text(script, encoding="utf-8")
    subject = tmp_path / "subject.py"
    subject.write_text(SOLVER + 'é = f"é{{x}} {1 + 1:>{2}}"\n', encoding="utf-8")
    done = subprocess.run(
        [str(other), "-I", str(probe), str(subject)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(done.stdout) == [normalised_source(subject.read_text(encoding="utf-8"))]
