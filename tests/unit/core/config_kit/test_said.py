"""Where the warnings of a validator go while a check collects them."""

from __future__ import annotations

import pytest

from hydromodpy.core.config_kit.said import Said, collecting, say


def _said_in_a_thread(texts: list[str], results: dict[str, list[Said]], key: str) -> None:
    with collecting() as said:
        for text in texts:
            say(text)
    results[key] = said


def test_the_sink_is_closed_after_an_exception() -> None:
    with pytest.raises(RuntimeError), collecting():
        raise RuntimeError("stop")
    with pytest.warns(UserWarning, match="back to warning"):
        say("back to warning")
