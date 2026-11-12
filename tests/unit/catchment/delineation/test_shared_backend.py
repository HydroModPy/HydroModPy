"""The one Whitebox facade of the process, shared by every caller.

The package builds a single backend on first use and keeps it until the cache is
cleared. It must not load the native library at import, since Whitebox is an optional extra.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy.catchment.delineation as delineation
from hydromodpy.catchment.delineation import (
    backend_has_callables,
    clear_whitebox_backend_cache,
    get_whitebox_backend,
    resolve_delineation_backend,
)
from hydromodpy.catchment.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend

# The whitebox_workflows native binding is not safe under pytest-xdist fork distribution.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

REPO_ROOT = Path(__file__).resolve().parents[4]

READABLE = SimpleNamespace(read=lambda: None, write=None)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_whitebox_backend_cache()
    yield
    clear_whitebox_backend_cache()


def test_backend_cached_until_cleared():
    first = get_whitebox_backend()
    assert isinstance(first, WhiteboxWorkflowsBackend)
    assert get_whitebox_backend() is first
    clear_whitebox_backend_cache()
    assert get_whitebox_backend() is not first


def test_injected_backend_wins():
    injected = object()
    assert resolve_delineation_backend(injected) is injected
    assert resolve_delineation_backend() is get_whitebox_backend()


CAPABILITIES = [
    pytest.param(SimpleNamespace(), ("read",), False, id="no component"),
    pytest.param(SimpleNamespace(raster=READABLE), ("read",), True, id="every method callable"),
    pytest.param(
        SimpleNamespace(raster=READABLE), ("read", "write"), False, id="a method not callable"
    ),
]


@pytest.mark.parametrize(("backend", "methods", "expected"), CAPABILITIES)
def test_backend_capability(backend, methods, expected):
    assert backend_has_callables(backend, "raster", *methods) is expected


def test_missing_dependency_is_named(monkeypatch):
    module = "hydromodpy.catchment.delineation.whitebox_workflows_backend"
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(ImportError, match="'whitebox_workflows' is not available"):
        get_whitebox_backend()


@pytest.mark.allow_subprocess
def test_import_does_not_load_whitebox():
    # A fresh interpreter, because this process has loaded the library long ago.
    probe = (
        "import sys\n"
        "import hydromodpy.catchment.delineation\n"
        "print('whitebox_workflows' in sys.modules)\n"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    ).stdout.strip()
    assert loaded == "False"


def test_registry_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"{delineation.__name__}.registry")


@pytest.mark.parametrize(
    "name", ["WhiteboxWorkflowsBackend", "WhiteboxRasterBackend", "get_backend"]
)
def test_backend_classes_not_exported(name):
    assert not hasattr(delineation, name)
