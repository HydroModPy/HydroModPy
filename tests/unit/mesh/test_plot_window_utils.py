from __future__ import annotations

from hydromodpy.spatial.mesh.plot_window_utils import maximize_figure_window


class _Canvas:
    def __init__(self, manager) -> None:
        self.manager = manager


class _Figure:
    def __init__(self, manager) -> None:
        self.canvas = _Canvas(manager)


class _QtWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def showMaximized(self) -> None:
        self.calls.append("showMaximized")


class _TkWindow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def state(self, value: str) -> None:
        self.calls.append(("state", value))


class _GeometryWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def geometry(self, value: str) -> None:
        self.calls.append(value)


class _WxFrame:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def Maximize(self, value: bool) -> None:
        self.calls.append(value)


def test_maximize_figure_window_prefers_qt_show_maximized() -> None:
    manager = type("Manager", (), {"window": _QtWindow()})()
    fig = _Figure(manager)

    maximize_figure_window(fig)

    assert manager.window.calls == ["showMaximized"]


def test_maximize_figure_window_uses_tk_zoomed_state() -> None:
    manager = type("Manager", (), {"window": _TkWindow()})()
    fig = _Figure(manager)

    maximize_figure_window(fig)

    assert manager.window.calls == [("state", "zoomed")]


def test_maximize_figure_window_falls_back_to_screen_geometry() -> None:
    manager = type("Manager", (), {"window": _GeometryWindow()})()
    fig = _Figure(manager)

    maximize_figure_window(fig)

    assert manager.window.calls == ["1920x1080+0+0"]


def test_maximize_figure_window_falls_back_to_wx_frame() -> None:
    manager = type("Manager", (), {"frame": _WxFrame()})()
    fig = _Figure(manager)

    maximize_figure_window(fig)

    assert manager.frame.calls == [True]
