"""A case figure opens maximised on whatever window toolkit matplotlib runs on."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.spatial.geographic.cases.plotting_utils import maximize_figure_window


class _Window:
    def __init__(self) -> None:
        self.calls: list[object] = []


class _Qt(_Window):
    def showMaximized(self) -> None:
        self.calls.append("showMaximized")


class _Tk(_Window):
    def state(self, value: str) -> None:
        self.calls.append(("state", value))


class _Geometry(_Window):
    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def geometry(self, value: str) -> None:
        self.calls.append(value)


class _Wx(_Window):
    def Maximize(self, value: bool) -> None:
        self.calls.append(value)


@pytest.mark.parametrize(
    ("attribute", "window", "expected"),
    [
        ("window", _Qt, ["showMaximized"]),
        ("window", _Tk, [("state", "zoomed")]),
        ("window", _Geometry, ["1920x1080+0+0"]),
        ("frame", _Wx, [True]),
    ],
    ids=["qt", "tk-zoomed", "screen-geometry", "wx-frame"],
)
def test_maximize_figure_window_uses_the_call_its_toolkit_knows(
    attribute, window, expected
) -> None:
    opened = window()
    manager = SimpleNamespace(**{attribute: opened})

    maximize_figure_window(SimpleNamespace(canvas=SimpleNamespace(manager=manager)))

    assert opened.calls == expected
