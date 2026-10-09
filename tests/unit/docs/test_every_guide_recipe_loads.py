"""Every TOML recipe a guide ships loads on top of the example 04 file it targets.

A guide offers its recipes for download and says to save them in the folder of
example 04. Each one is copied there, in a scratch folder, next to the files of
example 04 and read by the check of ``hmp config check``, which picks the schema by
``workflow.mode``. A key renamed in the model, or a date outside the example, breaks
this test and not the reader's first run. A key the loader only accepts with a rename
warning counts as broken too.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import tomllib
import warnings
from pathlib import Path

import pytest

from hydromodpy.cli.commands.config import _cmd_config_check
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

ROOT = Path(__file__).resolve().parents[3]
RECIPES = ROOT / "docs" / "source" / "guides" / "recipes"
EX04 = ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
FILES = sorted(RECIPES.rglob("*.toml"))
# Files a recipe names next to itself and that are not TOML (they are not loaded here).
SIDE_SUFFIXES = {".geojson", ".csv"}


def _id(path: Path) -> str:
    return path.relative_to(RECIPES).as_posix()


def _stage(recipe: Path, folder: Path) -> Path:
    """Put example 04, the other recipes of the folder and their side files in one folder."""
    for source in EX04.glob("*.toml"):
        shutil.copy(source, folder / source.name)
    for source in recipe.parent.iterdir():
        if source.suffix == ".toml" or source.suffix in SIDE_SUFFIXES:
            shutil.copy(source, folder / source.name)
    return folder / recipe.name


def test_the_recipes_are_found() -> None:
    assert len(FILES) >= 18
    assert any(p.parent.name == "model" for p in FILES)


@pytest.mark.parametrize("recipe", FILES, ids=_id)
def test_a_recipe_names_a_base_that_exists(recipe: Path) -> None:
    base = tomllib.loads(recipe.read_text(encoding="utf-8")).get("base_config")
    if base is None:
        return
    assert (EX04 / base).exists() or (recipe.parent / base).exists(), (
        f"{_id(recipe)} inherits {base}, which is neither a file of example 04 nor a recipe beside it"
    )


@pytest.mark.parametrize("recipe", FILES, ids=_id)
def test_a_recipe_loads_beside_example_04(recipe: Path, tmp_path: Path) -> None:
    staged = _stage(recipe, tmp_path)
    said = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConfigKeyRenamedWarning)
        try:
            with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
                _cmd_config_check(argparse.Namespace(file=staged))
        except SystemExit as stop:
            assert stop.code in (0, None), " ".join(said.getvalue().split())[:600]
