"""The base class of every configuration model: refused keys, frozen copies, schema examples.

Every model forbids unknown keys, so a key that moves is a hard break for every project
file. ``warn_old_form`` tells the reader of the file what to write instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import Field, PrivateAttr, ValidationError

from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    HydroModelBase,
    frozen_copy,
    thawed_copy,
    warn_old_form,
)
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.exceptions import FrozenConfigError


class _Inner(HydroModelBase):
    depth: float = 1.0


class _Cfg(HydroModelBase):
    model_refused_keys = {"mode": "use 'engine' instead"}

    engine: str = "grid"
    verbose: bool = False
    inner: _Inner = _Inner()
    rows: list[_Inner] = []
    table: dict[str, _Inner] = {}
    kind: Literal["a", "b"] = "a"
    path: Path = Path("data/in.csv")
    count: int = 3
    label: str | None = None


def test_visible_when_needs_sibling() -> None:
    class _Bad(HydroModelBase):
        a: Annotated[int, VisibleWhen("ghost", "x")] = 1

    with pytest.raises(ValidationError, match="references unknown sibling 'ghost'"):
        _Bad()


class _Engine(HydroModelBase):
    """A model whose ``engine`` key used to be called ``method``."""

    engine: str = Field(default="grid", description="Optimizer name.")


def test_unknown_key_refused() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _Engine.model_validate({"methode": "optuna"})


def test_assignment_validated() -> None:
    cfg = _Cfg()
    with pytest.raises(ValidationError):
        cfg.count = "many"  # type: ignore[assignment]


def test_frozen_copy_refuses_assignment() -> None:
    cfg = _Cfg(rows=[_Inner()], table={"a": _Inner()})
    frozen = frozen_copy(cfg)
    assert frozen == cfg
    for target in (frozen, frozen.inner, frozen.rows[0], frozen.table["a"]):
        with pytest.raises(FrozenConfigError, match="frozen copy of the configuration"):
            target.__setattr__("depth" if isinstance(target, _Inner) else "count", 5.0)
    cfg.count = 9
    assert frozen.count == 3


def test_schema_profile_and_examples() -> None:
    props = _Cfg.model_json_schema()["properties"]
    assert props["engine"]["x-hmp-profile"] == "user"
    assert props["engine"]["examples"] == ["grid"]
    assert props["kind"]["examples"] == ["a"]
    assert props["verbose"]["examples"] == [False]
    assert props["count"]["examples"] == [3]
    assert props["path"]["examples"] == ["data/input.csv"]


@pytest.mark.parametrize(
    ("annotation", "default", "expected"),
    [
        (str, ..., ["example"]),
        (int, ..., [1]),
        (float, ..., [1.0]),
        (bool, ..., [False]),
        (Path, ..., ["data/input.csv"]),
        (list[int], ..., None),
    ],
)
def test_example_from_type(annotation, default, expected) -> None:
    class _M(HydroModelBase):
        x: annotation = Field(default)  # type: ignore[valid-type]

    assert _M.model_json_schema()["properties"]["x"].get("examples") == expected


def test_enum_example_first_member() -> None:
    from enum import Enum

    class _Color(Enum):
        RED = "red"
        BLUE = "blue"

    class _M(HydroModelBase):
        c: _Color = _Color.BLUE
        d: _Color

    props = _M.model_json_schema()["properties"]
    assert props["d"]["examples"] == ["red"]


def test_unmigratable_change_warning() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        warn_old_form("f.toml", f"x{CANNOT_REWRITE}y")
    assert str(caught[0].message) == f"f.toml: x{CANNOT_REWRITE}y."


class _Table(HydroModelBase):
    """Settings of one plugin."""

    steps: Annotated[int, Profile.EXPERT] = 4


class _Section(HydroModelBase):
    name: str = "x"
    _tables: dict[str, _Table] = PrivateAttr(default_factory=lambda: {"plugin": _Table()})

    @classmethod
    def named_tables(cls, *, shipped_only: bool) -> dict[str, type[HydroModelBase]]:
        return {"plugin": _Table}

    def held_tables(self) -> dict[str, _Table]:
        return self._tables


def test_frozen_named_tables() -> None:
    frozen = frozen_copy(_Section())

    with pytest.raises(FrozenConfigError):
        frozen.held_tables()["plugin"].steps = 8
    assert thawed_copy(frozen).held_tables()["plugin"].steps == 4
