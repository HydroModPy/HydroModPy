"""Where the warnings of a validator go while a check collects them."""

from __future__ import annotations

import threading
import warnings

import pytest

from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, warn_old_form
from hydromodpy.core.config_kit.said import Said, collecting, say


def _said_in_a_thread(texts: list[str], results: dict[str, list[Said]], key: str) -> None:
    with collecting() as said:
        for text in texts:
            say(text)
    results[key] = said


@pytest.mark.parametrize("category", [UserWarning, FutureWarning, ConfigKeyRenamedWarning])
def test_without_a_sink_it_warns_with_its_category_at_the_caller(category) -> None:
    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("always")
        say("from here", category)
    assert [(item.category, str(item.message)) for item in shown] == [(category, "from here")]
    assert shown[0].filename == __file__


def test_the_stacklevel_counts_from_the_caller_of_say() -> None:
    def middle() -> None:
        say("one up", stacklevel=2)

    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("always")
        middle()
    assert shown[0].filename == __file__


def test_with_a_sink_it_keeps_the_text_and_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with collecting() as said:
            say("kept", FutureWarning)
            say("again")
    assert said == [Said("kept", FutureWarning), Said("again", UserWarning)]


def test_an_old_form_goes_to_the_sink_under_its_category() -> None:
    with collecting() as said:
        warn_old_form("a.toml", "x -> y")
    assert [item.category for item in said] == [ConfigKeyRenamedWarning]
    assert said[0].text.startswith("a.toml: x -> y.")


def test_sinks_nest_and_the_outer_one_comes_back() -> None:
    with collecting() as outer:
        say("outer one")
        with collecting() as inner:
            say("inner")
        say("outer two")
    assert [item.text for item in inner] == ["inner"]
    assert [item.text for item in outer] == ["outer one", "outer two"]


def test_the_sink_is_closed_after_an_exception() -> None:
    with pytest.raises(RuntimeError), collecting():
        raise RuntimeError("stop")
    with pytest.warns(UserWarning, match="back to warning"):
        say("back to warning")


def test_two_threads_keep_their_own_sink() -> None:
    results: dict[str, list[Said]] = {}
    started = threading.Barrier(2)

    def run(key: str, texts: list[str]) -> None:
        started.wait()
        _said_in_a_thread(texts, results, key)

    first = [f"first {n}" for n in range(200)]
    second = [f"second {n}" for n in range(200)]
    threads = [
        threading.Thread(target=run, args=("a", first)),
        threading.Thread(target=run, args=("b", second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [item.text for item in results["a"]] == first
    assert [item.text for item in results["b"]] == second


def test_a_thread_started_inside_a_sink_does_not_write_to_it() -> None:
    seen: list[warnings.WarningMessage] = []

    def run() -> None:
        with warnings.catch_warnings(record=True) as shown:
            warnings.simplefilter("always")
            say("from the thread")
        seen.extend(shown)

    with collecting() as said:
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
    assert said == []
    assert [str(item.message) for item in seen] == ["from the thread"]
