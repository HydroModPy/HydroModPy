"""A reference is a directory of the project tree, an id, or a selector.

The tree answers a directory name without the index. The index answers an id
and a selector, from its ``rel_dir`` and ``site`` columns and from the metric
rows scored under each run's metric rule.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import RUNS_DIRNAME, SESSIONS_DIRNAME
from hydromodpy.results.catalog import Catalog, index_new_runs
from hydromodpy.results.catalog.discovery import (
    AmbiguousReferenceError,
    SimulationNotFoundError,
    reference_rel_dir,
    resolve_rel_dir,
    resolve_trashed,
)
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.record import RunRecord
from hydromodpy.results.run.sealed import MixedWindowsError
from hydromodpy.results.trash import trash_run
from tests._helpers.sealed_runs import NOW, WINDOW, make_project, seal_run, write_attempt

AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)

MONTHLY = "11111111-0000-4000-8000-000000000001"
MONTHLY_V2 = "22222222-0000-4000-8000-000000000002"
BASE = "33333333-0000-4000-8000-000000000003"
HEX_NAMED = "44444444-0000-4000-8000-000000000004"


def _seal(
    root: Path,
    name: str,
    sim_id: str,
    *,
    site: str,
    day: int,
    nse: float | None,
    off_rule: dict[str, float] | None = None,
) -> None:
    """Seal one run; ``off_rule`` adds metric rows scored outside the metric rule."""
    seal_run(
        root,
        name,
        sim_id=sim_id,
        site=site,
        nse=nse,
        created_at=NOW - timedelta(days=30 - day),
    )
    if off_rule:
        directory = root / RUNS_DIRNAME / name
        record = RunRecord.read(directory)
        extra = [
            MetricRow(station=station, variable="stage", metric="nse", value=value)
            for station, value in off_rule.items()
        ]
        record.model_copy(update={"metrics": [*record.metrics, *extra]}).write(directory)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project with four sealed runs, one running attempt, and its index."""
    root = make_project(tmp_path / "p")
    _seal(root, "nancon_monthly", MONTHLY, site="nancon", day=1, nse=0.80)
    _seal(
        root,
        "nancon_monthly.v2",
        MONTHLY_V2,
        site="nancon",
        day=2,
        nse=0.60,
        off_rule={"lake": 0.95},
    )
    _seal(root, "J0014010-base", BASE, site="J0014010", day=3, nse=0.70)
    _seal(root, "beef1234", HEX_NAMED, site="nancon", day=4, nse=None)
    write_attempt(root, "runs/live", status="running", site="nancon", heartbeat_age_s=5)
    index_new_runs(root)
    return root


@pytest.fixture
def index(project: Path) -> Iterator[Catalog]:
    """The read-only facade over the index :func:`index_new_runs` built."""
    with Catalog(project) as catalog:
        yield catalog


def _make_dir(project: Path, rel_dir: str) -> Path:
    path = project / rel_dir
    path.mkdir(parents=True)
    return path


def test_a_bare_name_is_the_run_directory_and_a_path_names_itself() -> None:
    assert reference_rel_dir("nancon_monthly.v2") == "runs/nancon_monthly.v2"
    assert reference_rel_dir("J0014010-base") == "runs/J0014010-base"
    assert reference_rel_dir("sessions/calibration") == "sessions/calibration"
    assert (
        reference_rel_dir("sessions/calibration/trials/0004") == "sessions/calibration/trials/0004"
    )
    assert reference_rel_dir("@last") is None


def test_a_path_that_is_no_result_directory_says_which_forms_exist() -> None:
    with pytest.raises(SimulationNotFoundError, match="runs/<name>, sessions/<name>"):
        reference_rel_dir("figures/x")


def test_the_index_answers_a_directory_name_by_rel_dir(index: Catalog) -> None:
    assert index.resolve("nancon_monthly") == MONTHLY
    assert index.resolve("nancon_monthly.v2") == MONTHLY_V2
    assert index.resolve("runs/J0014010-base") == BASE


def test_a_bare_name_is_version_one_never_the_latest(index: Catalog) -> None:
    assert index.resolve("nancon_monthly") != index.resolve("nancon_monthly.v2")


def test_a_hex_word_that_is_a_name_and_an_id_prefix_is_ambiguous(project: Path) -> None:
    other = "beef1234-0000-4000-8000-000000000009"
    _seal(project, "J0014010-other", other, site="J0014010", day=5, nse=0.5)
    index_new_runs(project)
    with Catalog(project) as catalog, pytest.raises(AmbiguousReferenceError) as caught:
        catalog.resolve("beef1234")
    assert {key for key, _ in caught.value.candidates} == {other, HEX_NAMED}


def test_an_id_prefix_resolves(index: Catalog) -> None:
    assert index.resolve("3333") == BASE
    assert index.rel_dir_of(BASE) == "runs/J0014010-base"


def test_best_reads_the_metric_scored_under_the_rule_not_any_station(index: Catalog) -> None:
    # The lake row (0.95) carries no rule version: it never ranks a run as best.
    assert index.resolve("@best:nse", site="nancon") == MONTHLY
    assert index.resolve("@worst:nse", site="nancon") == MONTHLY_V2
    assert index.resolve("@best:nse@lake") == MONTHLY_V2
    # Two gauges are two rules: across sites the selector refuses unless forced.
    with pytest.raises(MixedWindowsError, match="J0014010"):
        index.resolve("@best:nse")
    assert index.resolve("@best:nse", mixed_windows=True) == MONTHLY


def test_a_selector_narrows_to_one_site(index: Catalog) -> None:
    assert index.resolve("@best:nse", site="J0014010") == BASE
    assert index.resolve("@last", site="J0014010") == BASE
    assert index.resolve("@last") == HEX_NAMED
    with pytest.raises(SimulationNotFoundError, match="runs/live has no sim_id yet"):
        index.resolve("@running")
    with pytest.raises(SimulationNotFoundError, match="site 'nowhere'"):
        index.resolve("@last", site="nowhere")


def test_an_unknown_name_suggests_the_closest_directories(index: Catalog) -> None:
    with pytest.raises(SimulationNotFoundError, match="nancon_monthly"):
        index.resolve("nancon_montly")


def test_find_filters_on_site_and_rule_metrics(index: Catalog) -> None:
    found = index.find(site="nancon", nse_gt=0.65)
    assert found.sim_ids == [MONTHLY]
    assert index.find(solver="modflow6", site="J0014010").sim_ids == [BASE]
    with pytest.raises(ValueError, match="site"):
        index.find(catchment="nancon")


def test_the_tree_answers_a_name_without_an_index(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_dir(project, f"{RUNS_DIRNAME}/nancon_monthly")
    _make_dir(project, f"{SESSIONS_DIRNAME}/calibration/trials/0004")
    assert resolve_rel_dir(project, "nancon_monthly") == "runs/nancon_monthly"
    assert (
        resolve_rel_dir(project, "sessions/calibration/trials/0004")
        == "sessions/calibration/trials/0004"
    )
    with pytest.raises(SimulationNotFoundError, match="is not a directory"):
        resolve_rel_dir(project, "nancon_daily")


def test_a_selector_without_an_index_says_how_to_build_one(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    with pytest.raises(SimulationNotFoundError, match="hmp catalog reindex"):
        resolve_rel_dir(project, "@best:nse")


def test_a_bare_name_with_other_versions_is_refused_when_it_must_be_unambiguous(
    tmp_path: Path,
) -> None:
    project = tmp_path / "p"
    _make_dir(project, "runs/J0014010-base")
    _make_dir(project, "runs/J0014010-base.v2")
    assert resolve_rel_dir(project, "J0014010-base") == "runs/J0014010-base"
    with pytest.raises(AmbiguousReferenceError) as caught:
        resolve_rel_dir(project, "J0014010-base", unambiguous=True)
    assert {key for key, _ in caught.value.candidates} == {
        "runs/J0014010-base",
        "runs/J0014010-base.v2",
    }
    assert resolve_rel_dir(project, "J0014010-base.v2", unambiguous=True) == "runs/J0014010-base.v2"
    assert resolve_rel_dir(project, "runs/J0014010-base", unambiguous=True) == "runs/J0014010-base"


def test_the_trash_answers_by_its_listing_name_or_by_the_directory(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _make_dir(project, "runs/nancon_daily")
    trashed = trash_run(project, "runs/nancon_daily", now=AT)
    assert resolve_trashed(project, "nancon_daily").path == trashed
    assert resolve_trashed(project, trashed.name).rel_dir == "runs/nancon_daily"
    _make_dir(project, "runs/nancon_daily")
    trash_run(project, "runs/nancon_daily", now=AT.replace(hour=10))
    with pytest.raises(AmbiguousReferenceError):
        resolve_trashed(project, "runs/nancon_daily")
    with pytest.raises(SimulationNotFoundError, match="hmp catalog trash"):
        resolve_trashed(project, "nancon_monthly")


def test_the_tree_asks_the_index_for_a_selector_and_an_id(project: Path) -> None:
    assert resolve_rel_dir(project, "@last") == "runs/beef1234"
    assert resolve_rel_dir(project, "@best:nse", site="nancon") == "runs/nancon_monthly"
    assert resolve_rel_dir(project, "@best:nse", site="J0014010") == "runs/J0014010-base"
    assert resolve_rel_dir(project, "@worst:nse", site="nancon") == "runs/nancon_monthly.v2"
    assert resolve_rel_dir(project, "3333") == "runs/J0014010-base"
    assert resolve_rel_dir(project, MONTHLY_V2) == "runs/nancon_monthly.v2"
    assert resolve_rel_dir(project, "@running", site="nancon") == "runs/live"
    with pytest.raises(SimulationNotFoundError, match="No running run in site 'J0014010'"):
        resolve_rel_dir(project, "@running", site="J0014010")


def test_a_directory_name_that_is_also_an_id_prefix_is_refused_by_the_tree(
    project: Path,
) -> None:
    (project / RUNS_DIRNAME / "2222").mkdir()
    with pytest.raises(AmbiguousReferenceError) as caught:
        resolve_rel_dir(project, "2222")
    assert {key for key, _ in caught.value.candidates} == {
        "runs/2222",
        "runs/nancon_monthly.v2",
    }
