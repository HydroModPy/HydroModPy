"""The surfaces of ``hydromodpy.data`` that a move must not change.

A reorganisation of the package moves modules, never what a user writes. These
tests pin that: the JSON schema of the ``[data]`` section and the data file the
wheel must ship. The package re-exports no name, so no public name is pinned
here. The source classes of ``hydromodpy.data.source`` are resolved
through its registry and not re-exported by the package, so their names are
pinned where they are read: at the registry, by ``test_data_source_registry``.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

DATA_SCHEMA_SHA256 = "681ea83667fd29e26f247547e7a4d91fdc4246611147fd166cdea6b7b9ce5ea9"


def test_the_data_config_schema_keeps_its_fingerprint() -> None:
    from hydromodpy.data.loading.config_schema import DataConfig

    schema = json.dumps(
        DataConfig.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(schema.encode("ascii")).hexdigest()

    assert digest == DATA_SCHEMA_SHA256, (
        "The JSON schema of [data] changed. If the change is intended, run "
        "`python -m tools.docs.schema_export`, then record the new digest here: "
        f"{digest}"
    )


@pytest.mark.parametrize(
    "shipped",
    ["hydromodpy/catchment/administrative/departement.gpkg"],
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
