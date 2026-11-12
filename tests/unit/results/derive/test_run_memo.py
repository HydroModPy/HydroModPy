"""One heavy comparison is built once per run and per knob.

Six figures of a gallery ask for the same comparison. On the Nancon at 25 m the
rebuild floods 345 260 cells and runs two full distance passes, which once took
longer than the solve.
"""

from __future__ import annotations

from hydromodpy.results.derive.run_memo import RunMemo


class Run:
    pass


def test_two_calls_on_one_run_return_the_same_object() -> None:
    memo = RunMemo()
    calls: list[int] = []
    run = Run()

    def build():
        calls.append(1)
        return object()

    first = memo.get_or_build(run, ("a",), build)
    second = memo.get_or_build(run, ("a",), build)

    assert first is second
    assert len(calls) == 1


def test_different_knob_is_a_different_entry() -> None:
    memo = RunMemo()
    run = Run()

    first = memo.get_or_build(run, ("a",), object)
    second = memo.get_or_build(run, ("b",), object)

    assert first is not second
