"""The one Whitebox facade of the process, and the helpers that read a backend."""

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


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_whitebox_backend_cache()
    yield
    clear_whitebox_backend_cache()


def test_the_backend_is_one_instance_until_the_cache_is_cleared():
    first = get_whitebox_backend()
    assert isinstance(first, WhiteboxWorkflowsBackend)
    assert get_whitebox_backend() is first
    clear_whitebox_backend_cache()
    assert get_whitebox_backend() is not first


def test_an_injected_backend_wins_over_the_shared_one() -> None:
    injected = object()
    assert resolve_delineation_backend(injected) is injected
    assert resolve_delineation_backend() is get_whitebox_backend()


_READ = SimpleNamespace(read=lambda: None, write=None)


@pytest.mark.parametrize(
    ("backend", "methods", "expected"),
    [
        (SimpleNamespace(), ("read",), False),
        (SimpleNamespace(raster=_READ), ("read",), True),
        (SimpleNamespace(raster=_READ), ("read", "write"), False),
    ],
    ids=["no-component", "every-method", "a-method-is-not-callable"],
)
def test_a_backend_has_a_capability_only_when_every_method_is_callable(
    backend, methods, expected
) -> None:
    assert backend_has_callables(backend, "raster", *methods) is expected


def test_a_missing_dependency_is_an_import_error_that_names_it(monkeypatch) -> None:
    """Whitebox is an optional extra, so its absence has to say which backend is out."""
    module = "hydromodpy.catchment.delineation.whitebox_workflows_backend"
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(ImportError, match="'whitebox_workflows' is not available"):
        get_whitebox_backend()


@pytest.mark.allow_subprocess
def test_importing_the_package_does_not_load_whitebox() -> None:
    """A fresh interpreter, because this process has loaded the library long ago."""
    probe = (
        "import sys\n"
        "import hydromodpy.catchment.delineation\n"
        "print('whitebox_workflows' in sys.modules)\n"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    ).stdout.strip()
    assert loaded == "False"


@pytest.mark.parametrize(
    "gone",
    ["registry", "WhiteboxWorkflowsBackend", "WhiteboxRasterBackend", "get_backend"],
)
def test_the_registry_and_the_lazy_class_names_are_gone(gone) -> None:
    """The package has one backend and no registry, and it holds no class of the backend."""
    if gone == "registry":
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"{delineation.__name__}.{gone}")
    else:
        assert not hasattr(delineation, gone)
