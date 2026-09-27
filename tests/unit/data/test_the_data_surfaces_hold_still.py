"""The surfaces of ``hydromodpy.data`` that a move must not change.

A reorganisation of the package moves modules, never what a user writes or
imports. These tests pin that: the JSON schema of
the ``[data]`` section, every public name, and the two data files the wheel
must ship.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

from hydromodpy._lazy import LAZY_IMPORTS

REPO_ROOT = Path(__file__).resolve().parents[3]

DATA_SCHEMA_SHA256 = "f15b3021ce125d38f89de7049cbe9f4150681a3bb42bf0add3f2b022d2877ca9"


def test_the_data_config_schema_keeps_its_fingerprint() -> None:
    from hydromodpy.data import DataManagersConfig

    schema = json.dumps(
        DataManagersConfig.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(schema.encode("ascii")).hexdigest()

    assert digest == DATA_SCHEMA_SHA256, (
        "The JSON schema of [data] changed. If the change is intended, run "
        "`python -m tools.doc_config`, then record the new digest here: "
        f"{digest}"
    )


def _public_data_names() -> list[tuple[str, str]]:
    from hydromodpy import data
    from hydromodpy.data import source

    names = [("hydromodpy.data", name) for name in data.__all__]
    names += [
        ("hydromodpy", name)
        for name, target in sorted(LAZY_IMPORTS.items())
        if target.startswith("hydromodpy.data.")
    ]
    names += [("hydromodpy.data.source", name) for name in source.__all__]
    return names


@pytest.mark.parametrize(("module", "name"), _public_data_names())
def test_every_public_data_name_resolves(module: str, name: str) -> None:
    assert getattr(importlib.import_module(module), name) is not None


@pytest.mark.parametrize(
    "shipped",
    [
        "hydromodpy/data/registry/migrations/0001_initial.sql",
        "hydromodpy/spatial/administrative/departement.gpkg",
    ],
)
def test_the_wheel_ships_the_data_files(shipped: str) -> None:
    path = REPO_ROOT / shipped
    assert path.is_file(), f"{shipped} is gone"
    package_dir = path.parent
    assert (package_dir / "__init__.py").is_file(), f"{package_dir} is not a package"

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    package = ".".join(package_dir.relative_to(REPO_ROOT).parts)
    patterns = package_data.get(package, [])

    assert any(fnmatch(path.name, pattern) for pattern in patterns), (
        f"pyproject.toml [tool.setuptools.package-data] has no pattern for {path.name} "
        f"under {package!r}"
    )
