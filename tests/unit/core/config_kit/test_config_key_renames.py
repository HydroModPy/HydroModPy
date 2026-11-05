"""Renaming a TOML key must not break the files that already use it.

Every configuration model forbids unknown keys, and nothing in the repository
declares an alias or a deprecation. A rename was therefore a hard break for every
project file at once, which is why several keys that say the wrong thing are
still called what they are called.

The seam is declarative: a model lists what a key used to be called, the old
spelling keeps loading, and using it warns with both names so a reader knows what
to write instead.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from pydantic import Field

import hydromodpy
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, HydroModelBase


class _Engine(HydroModelBase):
    """A model whose ``engine`` key used to be called ``method``."""

    model_legacy_keys = {"method": "engine"}

    engine: str = Field(default="grid", description="Optimizer name.")


def test_the_canonical_key_loads_without_a_word() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _Engine.model_validate({"engine": "optuna"}).engine == "optuna"


def test_the_old_key_still_loads() -> None:
    with pytest.warns(ConfigKeyRenamedWarning):
        assert _Engine.model_validate({"method": "optuna"}).engine == "optuna"


def test_the_warning_names_both_spellings() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        _Engine.model_validate({"method": "optuna"})

    message = str(caught[0].message)
    assert "method" in message
    assert "engine" in message


def test_declaring_both_is_refused() -> None:
    """Two spellings of one key in one file is a contradiction, not a merge."""
    with pytest.raises(ValueError, match="both"):
        _Engine.model_validate({"method": "optuna", "engine": "grid"})


def test_an_unknown_key_is_still_refused() -> None:
    """The seam widens nothing: only the declared old spellings are accepted."""
    with pytest.raises(ValueError):
        _Engine.model_validate({"methode": "optuna"})


def test_a_model_without_renames_is_untouched() -> None:
    class _Plain(HydroModelBase):
        value: int = 1

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _Plain.model_validate({"value": 3}).value == 3


# Python's own filters when no -W option is given, first match wins: a
# DeprecationWarning raised outside __main__ is dropped before anything prints it.
_PYTHON_DEFAULT_FILTERS = (
    ("default", DeprecationWarning, "__main__"),
    ("ignore", DeprecationWarning, ""),
    ("ignore", PendingDeprecationWarning, ""),
    ("ignore", ImportWarning, ""),
    ("ignore", ResourceWarning, ""),
)


def test_the_warning_survives_python_s_default_filters() -> None:
    """The rename reaches the reader of `hmp config check`, not only a test run."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.resetwarnings()
        for action, category, module in reversed(_PYTHON_DEFAULT_FILTERS):
            warnings.filterwarnings(action, category=category, module=module)
        _Engine.model_validate({"method": "optuna"})

    assert [item.category for item in caught] == [ConfigKeyRenamedWarning]
    assert issubclass(ConfigKeyRenamedWarning, FutureWarning)


def test_the_warning_is_dated_inside_the_package() -> None:
    """The console routing hides a deprecation a dependency raises about itself.

    Dated at pydantic's frame, the rename would be read as one and demoted to
    DEBUG, so it names the package's own file.
    """
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        _Engine.model_validate({"method": "optuna"})

    package = Path(hydromodpy.__file__).resolve().parent
    assert Path(caught[0].filename).resolve().is_relative_to(package)
