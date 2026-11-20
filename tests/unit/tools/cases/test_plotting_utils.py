"""A case figure opens maximized on whatever window toolkit matplotlib runs on."""

from types import SimpleNamespace

import pytest

from tools.cases.plotting_utils import maximize_figure_window


@pytest.mark.parametrize(
    ("attribute", "method", "expected"),
    [
        pytest.param("window", "showMaximized", ("showMaximized",), id="qt"),
        pytest.param("window", "state", ("state", "zoomed"), id="tk-zoomed"),
        pytest.param("window", "geometry", ("geometry", "1920x1080+0+0"), id="screen-geometry"),
        pytest.param("frame", "Maximize", ("Maximize", True), id="wx-frame"),
    ],
)
def test_maximize_figure_window_uses_the_call_its_toolkit_knows(
    attribute, method, expected
) -> None:
    calls: list[tuple] = []
    opened = SimpleNamespace(
        winfo_screenwidth=lambda: 1920,
        winfo_screenheight=lambda: 1080,
        **{method: lambda *args: calls.append((method, *args))},
    )
    manager = SimpleNamespace(**{attribute: opened})
    maximize_figure_window(SimpleNamespace(canvas=SimpleNamespace(manager=manager)))
    assert calls == [expected]
