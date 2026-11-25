"""The board of a ``[sites]`` launch: what is prepared, running, done and left.

``hmp run`` on a ``[sites]`` project hands a :class:`LaunchBoard` to the
launcher, which calls it with every line of its journal. On a terminal the
board redraws once a second: the prepare phase, a bar over the cases with the
time left, and one line per running case with the step it is on and, while
MODFLOW solves, its stress periods. The step comes from the progress events
each case writes to ``jobs/<stamp>-local/progress/``. Without a terminal, in
a log file or the output of a scheduler, the board prints one line per
finished case instead. It only reads: what it shows is never needed to run.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.live import Live
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from hydromodpy.core.console import progress
from hydromodpy.core.console.progress import format_duration
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

TAIL_BYTES = 8192
"""How much of the end of a progress file is read for its last event."""

READ_EVERY_S = 2.0
"""How often the progress file of one running case is read again."""

ROWS_KEPT_FREE = 9
"""Terminal lines left for the header and the bars above the running cases."""


@dataclass
class _Running:
    """A case whose child runs, and the last progress event read from it."""

    started: float
    progress: Path | None
    phase: str
    event: dict[str, Any] | None = None
    read_at: float = 0.0


@dataclass
class _State:
    """What the journal said so far."""

    plan_hash: str = ""
    n_cases: int = 0
    parallel: int = 1
    began: float = field(default_factory=time.monotonic)
    prepare_started: dict[str, float] = field(default_factory=dict)
    prepared: Counter[str] = field(default_factory=Counter)
    shared: int = 0
    prepare_done_after: float | None = None
    running: dict[str, _Running] = field(default_factory=dict)
    ended: Counter[str] = field(default_factory=Counter)
    durations: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _last_event(path: Path) -> dict[str, Any] | None:
    """Return the last whole JSON line of a progress file, or ``None``."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            return event
    return None


class LaunchBoard:
    """Show a ``[sites]`` launch from the lines of its journal.

    Call it with each journal line, inside ``with``. ``live`` draws the board on
    the terminal when the console allows it, and prints lines otherwise.
    """

    def __init__(self, *, live: bool = True) -> None:
        self._state = _State()
        self._lock = threading.Lock()
        self._live: Live | None = None
        self._want_live = live

    def __enter__(self) -> LaunchBoard:
        if self._want_live and progress.live_enabled():
            self._live = Live(self, console=progress.console, refresh_per_second=1, transient=False)
            self._live.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._live is not None:
            self._live.refresh()
            self._live.stop()

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            with self._lock:
                line = self._take(event)
        except Exception:  # noqa: BLE001 - the board shows the launch, it never stops it
            logger.debug("the launch board could not read %s", event, exc_info=True)
            return
        if line and self._live is None:
            print(line, file=sys.stderr, flush=True)

    def _take(self, event: dict[str, Any]) -> str | None:
        """Update the state from one journal line; return the line to print without a terminal."""
        state = self._state
        kind = event.get("event")
        case_id = str(event.get("case_id") or "")
        now = time.monotonic()
        if kind == "launch_start":
            state.plan_hash = str(event.get("plan_hash") or "")
            state.n_cases = int(event.get("n_cases") or 0)
            state.parallel = max(1, int(event.get("parallel") or 1))
            state.began = now
            return (
                f"[launch] plan {state.plan_hash}: {state.n_cases} cases, "
                f"{state.parallel} side by side"
            )
        if kind == "prepare_start":
            state.prepare_started[case_id] = now
            state.running[case_id] = _Running(now, _path(event.get("progress")), "prepare")
            return None
        if kind == "prepare_end":
            state.running.pop(case_id, None)
            status = str(event.get("status"))
            state.prepared[status] += 1
            if event.get("like"):
                state.shared += 1
                return None
            took = now - state.prepare_started.get(case_id, now)
            return f"[prepare] {case_id}: {status} in {format_duration(took)}"
        if kind == "lockfile":
            state.prepare_done_after = now - state.began
            return f"[prepare] {self._prepare_summary()}"
        if kind == "case_start":
            state.running[case_id] = _Running(now, _path(event.get("progress")), "run")
            return None
        if kind == "case_skipped":
            state.ended["skipped"] += 1
            return None
        if kind == "case_end":
            running = state.running.pop(case_id, None)
            status = str(event.get("status"))
            state.ended[status] += 1
            took = now - running.started if running is not None else 0.0
            if status == "completed":
                state.durations.append(took)
            else:
                state.failures.append(case_id)
            return (
                f"[{self._finished():>{len(str(state.n_cases))}}/{state.n_cases}] "
                f"{status:<9} {case_id}  {format_duration(took)}  | {self._counts_text()}"
            )
        return None

    def _finished(self) -> int:
        """Cases that will not run again in this launch."""
        failed_prepare = self._state.prepared["failed"]
        return sum(self._state.ended.values()) + failed_prepare

    def _counts_text(self) -> str:
        state = self._state
        failed = sum(n for status, n in state.ended.items() if status != "completed")
        failed += state.prepared["failed"]
        runs = sum(1 for case in state.running.values() if case.phase == "run")
        left = self._time_left()
        tail = "" if left is None else f", about {format_duration(left)} left"
        return f"{state.ended['completed']} completed, {failed} not, {runs} running{tail}"

    def _prepare_summary(self) -> str:
        state = self._state
        done = sum(state.prepared.values())
        own = done - state.shared
        text = f"{done} cases ready from {own} prepare{'s' if own != 1 else ''}"
        if state.prepared["failed"]:
            text += f", {state.prepared['failed']} failed"
        if state.prepare_done_after is not None:
            text += f" in {format_duration(state.prepare_done_after)}"
        return text

    def _time_left(self) -> float | None:
        """Estimate the time left from the mean duration of the completed cases."""
        state = self._state
        if not state.durations:
            return None
        mean = sum(state.durations) / len(state.durations)
        now = time.monotonic()
        running = [now - case.started for case in state.running.values() if case.phase == "run"]
        waiting = max(0, state.n_cases - self._finished() - len(running))
        work = waiting * mean + sum(max(mean - elapsed, 0.1 * mean) for elapsed in running)
        width = max(1, min(state.parallel, waiting + len(running)))
        return work / width

    def __rich__(self) -> RenderableType:
        with self._lock:
            return self._render()

    def _render(self) -> RenderableType:
        state = self._state
        now = time.monotonic()
        parts: list[RenderableType] = [
            Text.assemble(
                ("plan ", "dim"),
                (state.plan_hash, "bold"),
                (f"  ·  {state.n_cases} cases  ·  {state.parallel} side by side", "dim"),
            )
        ]
        bars = Table.grid(padding=(0, 2))
        bars.add_column(style="bold", width=8)
        bars.add_column(width=40)
        bars.add_column()
        prepared = sum(state.prepared.values())
        if state.prepare_done_after is not None:
            bars.add_row("prepare", Text("✓", style="green"), Text(self._prepare_summary()))
        elif state.prepare_started or prepared:
            preparing = [c for c in state.running.values() if c.phase == "prepare"]
            text = f"{prepared} cases ready, {len(preparing)} preparing"
            bars.add_row("prepare", ProgressBar(total=None, pulse=True), Text(text))
        finished = self._finished()
        failed = sum(n for status, n in state.ended.items() if status != "completed")
        failed += state.prepared["failed"]
        runs = [item for item in state.running.items() if item[1].phase == "run"]
        left = self._time_left()
        summary = Text.assemble(
            (f"{finished}/{state.n_cases}  ", "bold"),
            (f"✓ {state.ended['completed']}  ", "green"),
            (f"✗ {failed}  ", "red" if failed else "dim"),
            (f"▶ {len(runs)}  ", "cyan"),
            (f"{format_duration(now - state.began)}", "dim"),
            ("" if left is None else f"  ·  about {format_duration(left)} left", "dim"),
        )
        bars.add_row("runs", ProgressBar(total=max(1, state.n_cases), completed=finished), summary)
        parts.append(bars)
        if state.running:
            parts.append(self._running_table(now))
        if state.failures:
            shown = ", ".join(state.failures[-3:])
            more = len(state.failures) - 3
            parts.append(
                Text(f"not completed: {shown}" + (f" and {more} more" if more > 0 else ""), "red")
            )
        return Group(*parts)

    def _running_table(self, now: float) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan", no_wrap=True)
        table.add_column(no_wrap=True, max_width=28)
        table.add_column(width=24)
        table.add_column(justify="right", no_wrap=True)
        table.add_column(justify="right", style="dim", no_wrap=True)
        height = progress.console.size.height
        room = max(3, height - ROWS_KEPT_FREE)
        cases = sorted(self._state.running.items(), key=lambda item: item[1].started)
        for case_id, case in cases[:room]:
            event = self._event_of(case, now)
            step = str(event.get("stage")) if event else case.phase
            done, total = (event.get("step"), event.get("of")) if event else (None, None)
            if total:
                bar: RenderableType = ProgressBar(total=float(total), completed=float(done or 0))
                count = f"{int(done or 0)}/{int(total)}"
            else:
                bar, count = Text(""), ""
            table.add_row(case_id, step, bar, count, format_duration(now - case.started))
        if len(cases) > room:
            table.add_row(Text(f"… and {len(cases) - room} more", style="dim"), "", "", "", "")
        return table

    def _event_of(self, case: _Running, now: float) -> dict[str, Any] | None:
        """Return the last progress event of a running case, read at most every few seconds."""
        if case.progress is not None and now - case.read_at >= READ_EVERY_S:
            case.event = _last_event(case.progress) or case.event
            case.read_at = now
        return case.event


def _path(value: object) -> Path | None:
    """Return the progress file a journal line names, if any."""
    return Path(str(value)) if value else None


__all__ = ["LaunchBoard"]
