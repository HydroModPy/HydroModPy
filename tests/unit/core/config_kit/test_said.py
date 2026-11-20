"""Where the warnings of a validator go while a check collects them."""

from __future__ import annotations

import pytest

from hydromodpy.core.config_kit.said import collecting, say


def test_the_sink_is_closed_after_an_exception() -> None:
    with pytest.raises(RuntimeError), collecting():
        raise RuntimeError("stop")
    with pytest.warns(UserWarning, match="back to warning"):
        say("back to warning")
