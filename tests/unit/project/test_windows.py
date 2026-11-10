"""The windows of a long run: their names, their grids, their sources and their order."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import ConfigError, ResumeError
from hydromodpy.core.time.window import resolve_simulation_time_grid
from hydromodpy.project import windows as windows_module
from hydromodpy.project.request import RunOutcome, RunRequest
from hydromodpy.project.windows import (
    cut_grid,
    named_window,
    newest_sealed_run,
    recorded_window_source,
    run_windows,
    source_of,
    window_document,
    window_run_name,
    window_source_for,
)
from hydromodpy.results.manifest import InputEntry, is_sealed
from hydromodpy.results.storage.attempt import record_request_id
from hydromodpy.workflow.steps.prepare_solver.restart import WindowSource
from tests._helpers.run_stores import seal_demo_run


def _time(length: str | None = "6 months", window: Any = "all", end: str = "2020-12-31") -> Any:
    return SimpleNamespace(
        mode="explicit",
        start_datetime="2020-01-01",
        end_datetime=end,
        step_value=1,
        step_unit="month",
        coverage_policy="error",
        window_length=length,
        window=window,
    )


def _cfg(root: Path, *, length: str | None = "6 months", window: Any = "all", **time) -> Any:
    return SimpleNamespace(
        simulation=SimpleNamespace(name="island", time=_time(length, window, **time), process=None),
        workspace=SimpleNamespace(project_root=root, data_path=root / "data"),
    )


def _request(root: Path, **members: Any) -> RunRequest:
    document = {"simulation": {"time": {"window_length": "6 months"}}}
    return RunRequest(config=document, form="dict", **members)


# --- names and grids ---


@pytest.mark.parametrize(
    ("index", "count", "name"),
    [
        (1, 2, "island_w1"),
        (9, 9, "island_w9"),
        (1, 10, "island_w01"),
        (10, 10, "island_w10"),
        (7, 120, "island_w007"),
    ],
)
def test_a_window_is_named_with_its_number_padded_to_the_width_of_the_count(
    index: int, count: int, name: str
) -> None:
    assert window_run_name("island", index, count) == name


def test_the_runs_of_a_chain_sort_in_the_order_of_the_chain() -> None:
    names = [window_run_name("island", index, 12) for index in range(1, 13)]
    assert names == sorted(names)


@pytest.mark.parametrize(
    ("length", "window", "nper"),
    [
        (None, "all", 12),
        ("6 months", "all", 12),
        ("6 months", 1, 6),
        ("6 months", 2, 6),
        ("5 months", 3, 2),
        ("5 years", 1, 12),
    ],
    ids=["no chain", "all", "first", "second", "short last", "longer than the run"],
)
def test_the_grid_of_a_run_is_the_whole_grid_or_the_grid_of_its_window(
    length: str | None, window: Any, nper: int
) -> None:
    whole = resolve_simulation_time_grid(SimpleNamespace(simulation=SimpleNamespace(time=_time())))
    grid, chain = cut_grid(whole, _time(length, window))
    assert grid.nper == nper
    assert (chain is None) == (length is None or window == "all")
    if chain is not None:
        assert (chain.index, grid.boundaries[0]) == (window, whole.boundaries[chain.first_period])


def test_a_window_that_does_not_exist_is_refused_with_the_number_of_windows() -> None:
    whole = resolve_simulation_time_grid(SimpleNamespace(simulation=SimpleNamespace(time=_time())))
    with pytest.raises(ConfigError, match=r"window = 3 .*into 2 window\(s\)"):
        cut_grid(whole, _time("6 months", 3))


def test_the_document_of_a_window_names_the_window_and_leaves_the_original_alone() -> None:
    original = {"simulation": {"time": {"window_length": "6 months", "window": "all"}}, "a": 1}
    cut = window_document(original, 2)
    assert cut["simulation"]["time"] == {"window_length": "6 months", "window": 2}
    assert original["simulation"]["time"]["window"] == "all"
    assert cut["a"] == 1


# --- sources ---


def test_the_source_of_a_window_is_the_newest_sealed_version_of_the_window_before(
    tmp_path: Path,
) -> None:
    seal_demo_run(tmp_path, "island_w1")
    seal_demo_run(tmp_path, "island_w1")
    seal_demo_run(tmp_path, "island_w2")
    (tmp_path / "runs" / "island_w1.v3").mkdir()

    assert newest_sealed_run(tmp_path, "island_w1") == tmp_path / "runs" / "island_w1.v2"
    assert newest_sealed_run(tmp_path, "island_w9") is None


def test_a_window_without_a_sealed_window_before_it_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ConfigError, match=r"window 3 starts from the final state of window 2; run window 2 first"
    ):
        window_source_for(
            _request(tmp_path),
            _cfg(tmp_path),
            base=tmp_path,
            environment=SimpleNamespace(),
            index=3,
            count=3,
            stem="island",
        )


@pytest.mark.parametrize(
    ("recorded", "refused"),
    [("rid-expected", False), ("rid-other", True), (None, True)],
    ids=["same request", "another configuration", "no request id recorded"],
)
def test_a_source_played_with_another_request_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded: str | None, refused: bool
) -> None:
    run_dir, _ = seal_demo_run(tmp_path, "island_w1")
    if recorded is not None:
        record_request_id(run_dir, recorded)
    monkeypatch.setattr(windows_module, "_expected_request_id", lambda *a, **k: "rid-expected")
    asked = dict(
        request=_request(tmp_path),
        cfg=_cfg(tmp_path),
        base=tmp_path,
        environment=SimpleNamespace(),
        index=2,
        count=2,
        stem="island",
    )

    if refused:
        with pytest.raises(ConfigError, match="was played with another configuration"):
            window_source_for(asked.pop("request"), asked.pop("cfg"), **asked)
        return
    source = window_source_for(asked.pop("request"), asked.pop("cfg"), **asked)
    assert source.run_dir == run_dir
    assert source.sim_id == source_of(run_dir).sim_id


# --- the chain ---


class _Play:
    """Stands for the worker of one run: records each window and seals a run for it."""

    def __init__(
        self, root: Path, *, identical: set[str] = frozenset(), stop_at: str | None = None
    ):
        self.root = root
        self.identical = identical
        self.stop_at = stop_at
        self.calls: list[tuple[str, int, Path | None, Any]] = []

    def __call__(self, request: RunRequest, *, window_source: WindowSource | None = None):
        name = request.name
        window = request.config["simulation"]["time"]["window"]
        self.calls.append(
            (
                name,
                window,
                None if window_source is None else window_source.run_dir,
                request.resume,
            )
        )
        if name == self.stop_at:
            raise KeyboardInterrupt("stop requested")
        run_dir = self.root / "runs" / name
        if not is_sealed(run_dir):
            # A resumed window ends sealed in the folder it stopped in.
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir, _ = seal_demo_run(self.root, name)
        return RunOutcome(
            name=name,
            run_dir=run_dir,
            sim_id="sim",
            request_id=None,
            status="completed",
            identical_to=name if name in self.identical else None,
            project_root=self.root,
        )


def _chain(tmp_path: Path, play: _Play, cfg: Any = None, **members: Any) -> RunOutcome | None:
    return run_windows(
        _request(tmp_path, **members),
        cfg=_cfg(tmp_path) if cfg is None else cfg,
        base=tmp_path,
        environment=SimpleNamespace(),
        play=play,
    )


def test_the_windows_are_played_in_order_each_from_the_run_before_it(tmp_path: Path) -> None:
    play = _Play(tmp_path)

    last = _chain(tmp_path, play)

    assert [(name, window) for name, window, *_ in play.calls] == [
        ("island_w1", 1),
        ("island_w2", 2),
    ]
    assert play.calls[0][2] is None, "the first window starts on its own"
    assert play.calls[1][2] == tmp_path / "runs" / "island_w1"
    assert last is not None and last.name == "island_w2"


def test_a_stop_in_a_window_ends_the_chain(tmp_path: Path) -> None:
    play = _Play(tmp_path, stop_at="island_w1")

    with pytest.raises(KeyboardInterrupt, match="stop requested"):
        _chain(tmp_path, play)

    assert [name for name, *_ in play.calls] == ["island_w1"]


def test_a_window_number_plays_that_window_alone_from_the_window_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, _ = seal_demo_run(tmp_path, "island_w1")
    record_request_id(run_dir, "rid-expected")
    monkeypatch.setattr(windows_module, "_expected_request_id", lambda *a, **k: "rid-expected")
    play = _Play(tmp_path)

    run_windows(
        _request(tmp_path),
        cfg=_cfg(tmp_path, window=2),
        base=tmp_path,
        environment=SimpleNamespace(),
        play=play,
    )

    assert [(name, window, source) for name, window, source, _ in play.calls] == [
        ("island_w2", 2, run_dir)
    ]


def test_a_window_alone_after_a_missing_window_is_refused_and_nothing_is_played(
    tmp_path: Path,
) -> None:
    play = _Play(tmp_path)
    with pytest.raises(ConfigError, match="run window 1 first"):
        run_windows(
            _request(tmp_path),
            cfg=_cfg(tmp_path, window=2),
            base=tmp_path,
            environment=SimpleNamespace(),
            play=play,
        )
    assert play.calls == []


def test_the_window_keys_are_written_in_the_document_and_not_set(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="--set cannot change simulation.time.window"):
        _chain(tmp_path, _Play(tmp_path), set={"simulation.time.window": 2})


def test_a_chain_is_named_after_the_run_and_a_request_without_a_name_is_refused(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    cfg.simulation.name = None
    with pytest.raises(ConfigError, match="names none"):
        run_windows(
            _request(tmp_path),
            cfg=cfg,
            base=tmp_path,
            environment=SimpleNamespace(),
            play=_Play(tmp_path),
        )


def test_a_named_chain_takes_the_name_of_the_request(tmp_path: Path) -> None:
    play = _Play(tmp_path)
    _chain(tmp_path, play, name="long")
    assert [name for name, *_ in play.calls] == ["long_w1", "long_w2"]


def test_windows_already_sealed_are_told_once_each_but_the_last_is_left_to_the_caller(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="hydromodpy")
    play = _Play(tmp_path, identical={"island_w1", "island_w2"})

    last = _chain(tmp_path, play)

    told = [
        r.getMessage() for r in caplog.records if "identical to completed run" in r.getMessage()
    ]
    assert len(told) == 1 and "island_w1" in told[0]
    assert last is not None and last.identical_to == "island_w2"
    announced = [r.getMessage() for r in caplog.records if r.getMessage().startswith("window ")]
    assert announced == ["window 1 of 2: run island_w1", "window 2 of 2: run island_w2"]


# --- resume ---


def test_a_resume_continues_the_window_that_stopped_and_plays_the_others_plainly(
    tmp_path: Path,
) -> None:
    seal_demo_run(tmp_path, "island_w1")
    (tmp_path / "runs" / "island_w2").mkdir()
    play = _Play(tmp_path, identical={"island_w1"})

    _chain(tmp_path, play, resume="island")

    assert [(name, resume) for name, _, _, resume in play.calls] == [
        ("island_w1", None),
        ("island_w2", "island_w2"),
    ]


def test_a_resume_with_no_window_to_continue_is_refused_and_nothing_is_played(
    tmp_path: Path,
) -> None:
    seal_demo_run(tmp_path, "island_w1")
    seal_demo_run(tmp_path, "island_w2")
    play = _Play(tmp_path)

    with pytest.raises(ResumeError, match="no window of this run holds an interrupted attempt"):
        _chain(tmp_path, play, resume="island")

    assert play.calls == []


@pytest.mark.parametrize(
    ("ref", "count", "run", "named"),
    [
        ("island_w2", 2, "island_w2", ("island", 2)),
        ("island_w02", 10, "island_w02", ("island", 2)),
        ("island_w02", 2, "island_w02", None),
        ("island_w3", 2, "island_w3", None),
        ("island_w2", 2, None, None),
        ("island", 2, "island", None),
        ("", 2, None, None),
        (None, 2, None, None),
    ],
    ids=[
        "a window of the chain",
        "padded to the width of the count",
        "padded wider than the count",
        "past the last window",
        "no run of that name",
        "the chain itself",
        "a bare resume",
        "no resume",
    ],
)
def test_a_resume_names_a_window_when_it_is_the_name_of_a_run_of_that_window(
    tmp_path: Path, ref: str | None, count: int, run: str | None, named: Any
) -> None:
    if run is not None:
        (tmp_path / "runs" / run).mkdir(parents=True)
    assert named_window(ref, count, tmp_path) == named


def _stopped_in_window_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seal window 1 with the request the document asks, and leave window 2 stopped."""
    run_dir, _ = seal_demo_run(tmp_path, "island_w1")
    record_request_id(run_dir, "rid-expected")
    monkeypatch.setattr(windows_module, "_expected_request_id", lambda *a, **k: "rid-expected")
    (tmp_path / "runs" / "island_w2").mkdir()
    return run_dir


def test_a_resume_by_the_name_of_the_window_continues_it_from_the_window_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _stopped_in_window_2(tmp_path, monkeypatch)
    play = _Play(tmp_path)

    _chain(tmp_path, play, resume="island_w2")

    assert play.calls == [("island_w2", 2, first, "island_w2")]


def test_a_resume_from_the_file_the_window_froze_goes_on_to_the_last_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _stopped_in_window_2(tmp_path, monkeypatch)
    frozen = tmp_path / "runs" / "island_w2" / "config.toml"
    frozen.write_text("", encoding="utf-8")
    play = _Play(tmp_path)

    _chain(
        tmp_path,
        play,
        cfg=_cfg(tmp_path, window=2, end="2021-06-30"),
        resume="island_w2",
        source=str(frozen),
    )

    assert [(name, window, source, resume) for name, window, source, resume in play.calls] == [
        ("island_w2", 2, first, "island_w2"),
        ("island_w3", 3, tmp_path / "runs" / "island_w2", None),
    ]


@pytest.mark.parametrize(
    ("window", "sealed", "match"),
    [
        (1, False, "names window 2, and the document plays window 1"),
        ("all", True, "that window holds no interrupted attempt"),
    ],
    ids=["another window in the document", "a window sealed already"],
)
def test_a_resume_by_the_name_of_a_window_it_cannot_continue_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: Any, sealed: bool, match: str
) -> None:
    _stopped_in_window_2(tmp_path, monkeypatch)
    (tmp_path / "runs" / "island_w3").mkdir()
    if sealed:
        (tmp_path / "runs" / "island_w2").rmdir()
        seal_demo_run(tmp_path, "island_w2")
    play = _Play(tmp_path)

    with pytest.raises(ResumeError, match=match):
        _chain(
            tmp_path,
            play,
            cfg=_cfg(tmp_path, window=window, end="2021-06-30"),
            resume="island_w2",
        )

    assert play.calls == []


def test_the_source_check_applies_the_set_of_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, _ = seal_demo_run(tmp_path, "island_w1")
    seen: dict[str, Any] = {}

    class _Loaded:
        workspace = SimpleNamespace(project_root=tmp_path, data_path=tmp_path / "data")
        changes: dict[str, Any] = {}

        def with_changes(self, changes: dict[str, Any]) -> _Loaded:
            changed = _Loaded()
            changed.changes = changes
            return changed

    def request_id(cfg: Any, resolved: Any, **_: Any) -> str:
        seen.update(cfg.changes)
        return "rid"

    monkeypatch.setattr("hydromodpy.config.loading.load", lambda *a, **k: _Loaded())
    monkeypatch.setattr("hydromodpy.data.loading.inputs.resolve_inputs", lambda *a, **k: None)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.prepare_solver.restart.source_state_digests",
        lambda *a, **k: {},
    )
    monkeypatch.setattr("hydromodpy.workflow.solution_key.request_id_of", request_id)

    found = windows_module._expected_request_id(
        _request(tmp_path, set={"flow.param.K.field.value": 1e-5}),
        _cfg(tmp_path),
        run_dir,
        base=tmp_path,
        environment=SimpleNamespace(bounds=None),
        index=1,
    )

    assert found == "rid"
    assert seen == {"flow.param.K.field.value": 1e-5}


@pytest.mark.parametrize(
    ("row", "found"),
    [
        (None, None),
        ("runs/island_w1/final_state", "island_w1"),
        ("runs/island_w9/final_state", ConfigError),
    ],
    ids=["a window that started on its own", "the window before", "a source no longer there"],
)
def test_a_sealed_window_replays_from_the_source_its_inputs_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: str | None, found: Any
) -> None:
    seal_demo_run(tmp_path, "island_w1")
    second, _ = seal_demo_run(tmp_path, "island_w2")
    rows = [InputEntry(variable="recharge", provider="file", path="data/recharge.csv")]
    if row is not None:
        rows.append(InputEntry(variable="initial_state", provider="run", path=row))
    monkeypatch.setattr(windows_module, "read_inputs", lambda run_dir: SimpleNamespace(inputs=rows))

    if found is ConfigError:
        with pytest.raises(ConfigError, match="started from runs/island_w9/final_state"):
            recorded_window_source(second, tmp_path)
        return
    source = recorded_window_source(second, tmp_path)
    if found is None:
        assert source is None
        return
    assert source == source_of(tmp_path / "runs" / found)


# --- the verb routes a document that cuts its run ---


def test_the_worker_verb_plays_the_windows_of_a_document_that_cuts_its_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy.project.dispatch.workflow as workflow

    play = _Play(tmp_path)
    monkeypatch.setattr(workflow, "_checked_environment", lambda environment, root: environment)
    monkeypatch.setattr(workflow, "_loaded", lambda request, base: _cfg(tmp_path))
    monkeypatch.setattr(
        workflow,
        "run_single_simulation",
        lambda request, *, window_source=None, **_kw: play(request, window_source=window_source),
    )

    last = workflow.run_simulation(_request(tmp_path), base=tmp_path, environment=SimpleNamespace())

    assert [(name, window) for name, window, *_ in play.calls] == [
        ("island_w1", 1),
        ("island_w2", 2),
    ]
    assert last is not None and last.name == "island_w2"


def test_the_worker_verb_counts_the_windows_with_the_set_of_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy.project.dispatch.workflow as workflow

    play = _Play(tmp_path)
    monkeypatch.setattr(workflow, "_checked_environment", lambda environment, root: environment)
    monkeypatch.setattr(workflow, "_loaded", lambda request, base: _cfg(tmp_path))
    monkeypatch.setattr(
        workflow,
        "_changed",
        lambda cfg, overrides: _cfg(tmp_path, end=overrides["simulation.time.end_datetime"]),
    )
    monkeypatch.setattr(
        workflow,
        "run_single_simulation",
        lambda request, *, window_source=None, **_kw: play(request, window_source=window_source),
    )

    workflow.run_simulation(
        _request(tmp_path, set={"simulation.time.end_datetime": "2021-06-30"}),
        base=tmp_path,
        environment=SimpleNamespace(),
    )

    assert [name for name, *_ in play.calls] == ["island_w1", "island_w2", "island_w3"]


def test_the_worker_verb_replays_a_sealed_window_from_the_source_it_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy.project.dispatch.workflow as workflow

    calls: list[dict] = []
    replayed = tmp_path / "runs" / "island_w2"
    source = WindowSource(run_dir=tmp_path / "runs" / "island_w1", sim_id="sim")
    monkeypatch.setattr(workflow, "_checked_environment", lambda environment, root: environment)
    monkeypatch.setattr(workflow, "_loaded", lambda request, base: _cfg(tmp_path, window=2))
    monkeypatch.setattr(
        windows_module,
        "recorded_window_source",
        lambda run_dir, root: source if run_dir == replayed else None,
    )
    monkeypatch.setattr(
        workflow, "run_single_simulation", lambda request, **kw: calls.append(kw) or "one run"
    )

    outcome = workflow.run_simulation(
        _request(tmp_path), base=tmp_path, environment=SimpleNamespace(), replay_of=replayed
    )

    assert outcome == "one run"
    assert len(calls) == 1 and calls[0]["window_source"] == source


def test_the_worker_verb_plays_one_run_for_a_document_that_does_not_cut_its_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy.project.dispatch.workflow as workflow

    calls: list[dict] = []
    monkeypatch.setattr(workflow, "_checked_environment", lambda environment, root: environment)
    monkeypatch.setattr(workflow, "_loaded", lambda request, base: _cfg(tmp_path, length=None))
    monkeypatch.setattr(
        workflow, "run_single_simulation", lambda request, **kw: calls.append(kw) or "one run"
    )

    outcome = workflow.run_simulation(
        _request(tmp_path), base=tmp_path, environment=SimpleNamespace()
    )

    assert outcome == "one run"
    assert len(calls) == 1 and calls[0].get("window_source") is None
