"""Pin what the architecture scanner sees, and what it refuses to see.

The layer-matrix gate is only as honest as this scanner. Two mechanisms carry
real cross-package edges that no import statement declares -- ``import_module``
on a literal and the PEP 562 lazy-attribute map -- and one mechanism, a string
argument of an arbitrary call, carries edges that are not imports at all.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_build_graph_under_test", _BUILD_GRAPH_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
build_graph = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = build_graph
_SPEC.loader.exec_module(build_graph)


@pytest.fixture
def pkg_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """A package named like the real one, with two sibling layers and an annex."""
    root = tmp_path / "hydromodpy"
    (root / "core").mkdir(parents=True)
    (root / "spatial").mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "spatial" / "__init__.py").write_text("", encoding="utf-8")
    (root / "spatial" / "engine.py").write_text("", encoding="utf-8")
    (root / "spatial" / "grid.py").write_text("", encoding="utf-8")
    annex = tmp_path / "hydromodpy_annex"
    annex.mkdir()
    (annex / "__init__.py").write_text("", encoding="utf-8")
    (annex / "preprocess.py").write_text("", encoding="utf-8")
    return root


def _kinds(edges: list) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for edge in edges:
        grouped.setdefault(edge.kind, []).append(edge)
    return grouped


def test_static_imports_are_still_seen(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "from hydromodpy.spatial import engine\nimport hydromodpy.spatial.grid\n",
        encoding="utf-8",
    )
    edges = build_graph.scan_package(pkg_root)
    assert {e.kind for e in edges} == {"from", "import"}
    assert all(e.src_pkg == "core" and e.tgt_pkg == "spatial" for e in edges)


def test_import_module_on_a_literal_is_an_edge(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\nmod = import_module('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    dynamic = _kinds(build_graph.scan_package(pkg_root))["import_module"]
    assert [(e.src_pkg, e.tgt_pkg, e.target_module) for e in dynamic] == [
        ("core", "spatial", "hydromodpy.spatial.engine")
    ]


def test_import_module_through_the_module_attribute_is_an_edge(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "import importlib\nmod = importlib.import_module('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    dynamic = _kinds(build_graph.scan_package(pkg_root))["import_module"]
    assert [e.target_module for e in dynamic] == ["hydromodpy.spatial.engine"]


def test_import_module_by_keyword_argument_is_an_edge(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "mod = import_module(name='hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    dynamic = _kinds(build_graph.scan_package(pkg_root))["import_module"]
    assert [e.target_module for e in dynamic] == ["hydromodpy.spatial.engine"]


def test_import_module_bound_under_another_name_is_an_edge(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module as _load\nmod = _load('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    dynamic = _kinds(build_graph.scan_package(pkg_root))["import_module"]
    assert [e.target_module for e in dynamic] == ["hydromodpy.spatial.engine"]


def test_an_unrelated_object_with_an_import_module_method_mints_nothing(
    pkg_root: pathlib.Path,
) -> None:
    """``loader.import_module(...)`` is not an import unless the receiver is importlib."""
    (pkg_root / "core" / "reader.py").write_text(
        "class Loader:\n"
        "    def import_module(self, name):\n"
        "        return name\n"
        "loaded = Loader().import_module('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_an_alias_bound_inside_a_function_does_not_leak(pkg_root: pathlib.Path) -> None:
    """A binding made in one scope must not claim a same-named parameter elsewhere."""
    (pkg_root / "core" / "reader.py").write_text(
        "def helper():\n"
        "    from importlib import import_module as _load\n"
        "    return _load\n"
        "def other(_load):\n"
        "    return _load('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_a_local_function_named_import_module_mints_nothing(pkg_root: pathlib.Path) -> None:
    """The name only counts when this file bound it to ``importlib``."""
    (pkg_root / "core" / "reader.py").write_text(
        "def import_module(label):\n"
        "    return label\n"
        "loaded = import_module('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_import_module_on_a_variable_is_invisible(pkg_root: pathlib.Path) -> None:
    """A runtime-computed name cannot be resolved, and is not guessed at."""
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "def load(name):\n"
        "    return import_module(f'hydromodpy.spatial.{name}')\n",
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_a_deferred_dynamic_import_is_reported_as_deferred(pkg_root: pathlib.Path) -> None:
    """An ``import_module`` inside a function is the way out of a cycle.

    Reporting it as unconditional top-level would misdescribe it exactly where
    the distinction matters.
    """
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "def load():\n"
        "    return import_module('hydromodpy.spatial.engine')\n"
        "_EAGER = {'Grid': 'hydromodpy.spatial.grid'}\n",
        encoding="utf-8",
    )
    by_kind = _kinds(build_graph.scan_package(pkg_root))
    assert by_kind["import_module"][0].in_function is True
    assert by_kind["lazy_map"][0].in_function is False


def test_a_decorator_argument_is_not_deferred(pkg_root: pathlib.Path) -> None:
    """A decorator runs when the ``def`` runs, so its import is eager."""
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "def deco(arg):\n"
        "    return lambda fn: fn\n"
        "@deco(import_module('hydromodpy.spatial.engine'))\n"
        "def target():\n"
        "    pass\n",
        encoding="utf-8",
    )
    dynamic = _kinds(build_graph.scan_package(pkg_root))["import_module"]
    assert [e.in_function for e in dynamic] == [False]


def test_a_default_argument_is_not_deferred(pkg_root: pathlib.Path) -> None:
    """A default value is evaluated once, when the ``def`` is executed."""
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "def target(engine=import_module('hydromodpy.spatial.engine')):\n"
        "    return engine\n",
        encoding="utf-8",
    )
    dynamic = _kinds(build_graph.scan_package(pkg_root))["import_module"]
    assert [e.in_function for e in dynamic] == [False]


def test_a_type_checking_dynamic_target_is_flagged(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    _HINTS = {'Engine': 'hydromodpy.spatial.engine'}\n",
        encoding="utf-8",
    )
    lazy = _kinds(build_graph.scan_package(pkg_root))["lazy_map"]
    assert lazy[0].in_type_checking is True


def test_the_else_branch_of_a_type_checking_block_is_runtime_code(
    pkg_root: pathlib.Path,
) -> None:
    """``else:`` under ``if TYPE_CHECKING:`` runs; only the body does not."""
    (pkg_root / "core" / "reader.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import hydromodpy.spatial.engine\n"
        "else:\n"
        "    import hydromodpy.spatial.grid\n",
        encoding="utf-8",
    )
    by_module = {e.target_module: e for e in build_graph.scan_package(pkg_root)}
    assert by_module["hydromodpy.spatial.engine"].in_type_checking is True
    assert by_module["hydromodpy.spatial.grid"].in_type_checking is False


def test_a_target_inside_a_lambda_is_deferred(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "load = lambda: import_module('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    edges = build_graph.scan_package(pkg_root)
    assert [e.in_function for e in edges] == [True]


def test_two_edges_on_one_line_are_judged_separately(pkg_root: pathlib.Path) -> None:
    """A line-keyed scope flag let one edge decide for its neighbour.

    Both edges below sit on the same physical line, one eager and one deferred.
    """
    (pkg_root / "core" / "reader.py").write_text(
        "from importlib import import_module\n"
        "_EAGER = {'Grid': 'hydromodpy.spatial.grid'}; "
        "load = lambda: import_module('hydromodpy.spatial.engine')\n",
        encoding="utf-8",
    )
    by_module = {e.target_module: e for e in build_graph.scan_package(pkg_root)}
    assert by_module["hydromodpy.spatial.grid"].in_function is False
    assert by_module["hydromodpy.spatial.engine"].in_function is True


def test_a_lazy_attribute_map_is_an_edge(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "__init__.py").write_text(
        "_LAZY_IMPORTS = {\n"
        '    "Engine": "hydromodpy.spatial.engine:Engine",\n'
        '    "Grid": "hydromodpy.spatial.grid",\n'
        "}\n",
        encoding="utf-8",
    )
    lazy = _kinds(build_graph.scan_package(pkg_root))["lazy_map"]
    assert [(e.tgt_pkg, e.target_module) for e in lazy] == [
        ("spatial", "hydromodpy.spatial.engine"),
        ("spatial", "hydromodpy.spatial.grid"),
    ]


def test_a_dict_value_that_is_not_a_module_mints_nothing(pkg_root: pathlib.Path) -> None:
    """Prose, another namespace, the bare package name, and a bad suffix."""
    (pkg_root / "core" / "reader.py").write_text(
        "PAYLOAD = {\n"
        '    "doc": "see hydromodpy.spatial.engine for details",\n'
        '    "other": "numpy.linalg",\n'
        '    "tool": "hydromodpy",\n'
        '    "attr": "hydromodpy.spatial.engine:Engine:extra",\n'
        "}\n",
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_a_dict_value_naming_no_module_on_disk_mints_nothing(pkg_root: pathlib.Path) -> None:
    """A schema identifier is shaped like a module and is not one.

    The real package writes three of them, e.g.
    ``"hydromodpy.calibration.params_hash.v2"``.
    """
    (pkg_root / "core" / "reader.py").write_text(
        'SCHEMAS = {"payload": "hydromodpy.spatial.engine_hash.v2"}\n',
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_a_string_argument_of_an_arbitrary_call_mints_nothing(pkg_root: pathlib.Path) -> None:
    """``getLogger("hydromodpy.warnings")`` names a logger, not a module.

    Scanning every call argument was measured against the real package: it
    reported a log file name and a logger name as ``core -> <root>`` edges.
    """
    (pkg_root / "core" / "reader.py").write_text(
        "import logging\n"
        "logger = logging.getLogger('hydromodpy.spatial.engine')\n"
        "path = 'hydromodpy.spatial.log'\n",
        encoding="utf-8",
    )
    assert build_graph.scan_package(pkg_root) == []


def test_an_unparsable_file_fails_loudly(pkg_root: pathlib.Path) -> None:
    broken = pkg_root / "core" / "broken.py"
    broken.write_text("def oops(:\n", encoding="utf-8")
    with pytest.raises(build_graph.UnparsableSource) as excinfo:
        build_graph.scan_package(pkg_root)
    assert "broken.py" in str(excinfo.value)


def test_a_file_with_undecodable_bytes_fails_loudly(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "binary.py").write_bytes(b"\xfe\xff\x00import os\n")
    with pytest.raises(build_graph.UnparsableSource):
        build_graph.scan_package(pkg_root)


def test_the_annex_direction_is_still_reported(pkg_root: pathlib.Path) -> None:
    (pkg_root / "core" / "reader.py").write_text(
        '_LAZY_IMPORTS = {"X": "hydromodpy_annex.preprocess:X"}\n',
        encoding="utf-8",
    )
    edges = build_graph.scan_package(pkg_root)
    assert [(e.kind, e.tgt_pkg) for e in edges] == [("lazy_map", "<annex>")]


def test_the_real_package_declares_every_lazy_edge_it_relies_on() -> None:
    """The scanner sees the maps of the shipped package, not only of fixtures."""
    edges = build_graph.scan_package(REPO_ROOT / "hydromodpy")
    lazy = [e for e in edges if e.kind == "lazy_map"]
    assert len(lazy) > 100, "the lazy-attribute maps of hydromodpy are not being resolved"
    by_module = {e.src_module for e in lazy}
    assert "hydromodpy._lazy" in by_module
    assert "hydromodpy.solver.base.registry" in by_module, "_BUILTIN_PATHS is not resolved"
