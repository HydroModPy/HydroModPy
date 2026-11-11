"""Moving a TOML key must not go unseen by the files that already use it.

Every configuration model forbids unknown keys, so a key that moves is a hard break
for every project file at once. The rows of ``schema/changes.toml`` say where a key
went, the migration reads a file under the new name, and ``warn_old_form`` tells the
reader of the file, with both names, what to write instead. This file holds what the
base of the models owes that seam: the warning reaches its reader, and a model never
accepts a key it does not hold.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from pydantic import Field

import hydromodpy
from hydromodpy.core.config_kit.base import (
    ConfigKeyRenamedWarning,
    HydroModelBase,
    warn_old_form,
)


class _Engine(HydroModelBase):
    """A model whose ``engine`` key used to be called ``method``."""

    engine: str = Field(default="grid", description="Optimizer name.")


def test_the_canonical_key_loads_without_a_word() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _Engine.model_validate({"engine": "optuna"}).engine == "optuna"


def test_a_moved_key_warns_the_reader_of_the_file() -> None:
    with pytest.warns(ConfigKeyRenamedWarning):
        warn_old_form("run.toml", "method -> engine")


def test_the_warning_names_both_spellings_and_the_doctor() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        warn_old_form("run.toml", "method -> engine")

    message = str(caught[0].message)
    assert "method -> engine" in message
    assert "hmp doctor --fix-config run.toml" in message


def test_the_old_key_is_not_accepted_by_the_model() -> None:
    """The base keeps no list of old spellings: the migration moves the key before it."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _Engine.model_validate({"method": "optuna"})


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
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
    """The move reaches the reader of `hmp check`, not only a test run."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.resetwarnings()
        for action, category, module in reversed(_PYTHON_DEFAULT_FILTERS):
            warnings.filterwarnings(action, category=category, module=module)
        warn_old_form("run.toml", "method -> engine")

    assert [item.category for item in caught] == [ConfigKeyRenamedWarning]
    assert issubclass(ConfigKeyRenamedWarning, FutureWarning)


def test_the_warning_is_dated_inside_the_package() -> None:
    """The console routing hides a deprecation a dependency raises about itself.

    Dated at a third party's frame, the move would be read as one and demoted to
    DEBUG, so it names the package's own file.
    """
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        warn_old_form("run.toml", "method -> engine")

    package = Path(hydromodpy.__file__).resolve().parent
    assert Path(caught[0].filename).resolve().is_relative_to(package)
