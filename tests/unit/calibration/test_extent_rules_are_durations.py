"""The two extent rules of a network output are durations, converted by the run's timestep.

``maximal_flowing_steps`` and ``minimal_dry_steps`` counted timesteps, so the
same file meant a day on a daily run and a month on a monthly one. Now the
output writes ``maximal_flowing_duration`` and ``minimal_dry_duration`` ("30 d",
"1 month") and the run counts its own timesteps: a flowing duration is rounded
up to whole steps (at least one), a dry one down (at least none). A key renamed
is refused with the new name, the doctor rewrites the file as ``N`` times the
``[simulation.time]`` step, and a sealed run config still reads.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibNetworkExtent
from hydromodpy.calibration.metrics.solver_extract import context_step_days
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.core.stream_extent import (
    dry_steps,
    flowing_steps,
    parse_extent_duration,
)
from hydromodpy.core.time import nominal_step_days
from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
from hydromodpy.results.derive.stream_extent import network_extents_from_run, run_step_days
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests.unit.config.test_a_renamed_key_is_refused_and_a_sealed_one_reads import (
    PROJECT,
    _project,
)
from tests.unit.results._transient_network_run import transient_run

DAY = nominal_step_days(1, "day")
MONTH = nominal_step_days(1, "month")


def _days(text: str) -> float:
    return parse_extent_duration(text)


# -- the file ----------------------------------------------------------------


def test_the_extent_names_two_durations_left_unwritten_by_default() -> None:
    extent = CalibNetworkExtent()

    assert (extent.maximal_flowing_duration, extent.minimal_dry_duration) == (None, None)
    assert "maximal_flowing_steps" not in CalibNetworkExtent.model_fields
    assert "minimal_dry_steps" not in CalibNetworkExtent.model_fields


def test_a_duration_is_read_with_its_unit() -> None:
    extent = CalibNetworkExtent(maximal_flowing_duration="1 month", minimal_dry_duration="0 d")

    assert (extent.maximal_flowing_duration, extent.minimal_dry_duration) == ("1 month", "0 d")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("maximal_flowing_duration", "30", "carries no unit"),
        ("maximal_flowing_duration", 30, "is not a duration"),
        ("maximal_flowing_duration", "0 d", "longer than zero"),
        ("minimal_dry_duration", "-1 d", "must not be negative"),
        ("minimal_dry_duration", "2 m", "not compatible"),
    ],
)
def test_a_duration_without_a_unit_or_out_of_range_is_refused(field, value, reason) -> None:
    with pytest.raises(ValidationError, match=reason):
        CalibNetworkExtent(**{field: value})


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("maximal_flowing_steps", "'maximal_flowing_duration'"),
        ("minimal_dry_steps", "'minimal_dry_duration'"),
    ],
)
def test_the_old_key_is_refused_with_the_name_that_replaces_it(old: str, new: str) -> None:
    with pytest.raises(ValidationError, match="is not accepted any more: renamed") as refused:
        CalibNetworkExtent(**{old: 1})

    assert new in str(refused.value)
    assert "hmp doctor --fix-config" in str(refused.value)


# -- the conversion ----------------------------------------------------------


def test_thirty_days_on_a_daily_run_are_thirty_timesteps() -> None:
    assert flowing_steps(_days("30 d"), DAY) == 30
    assert dry_steps(_days("30 d"), DAY) == 30


def test_a_month_on_a_monthly_run_is_one_timestep() -> None:
    assert flowing_steps(_days("1 month"), MONTH) == 1
    assert dry_steps(_days("1 month"), MONTH) == 1
    assert flowing_steps(_days("12 months"), MONTH) == 12


def test_forty_five_days_on_a_monthly_run_are_two_flowing_and_one_dry_timestep() -> None:
    assert flowing_steps(_days("45 d"), MONTH) == 2
    assert dry_steps(_days("45 d"), MONTH) == 1


def test_a_duration_shorter_than_a_timestep_keeps_the_least_a_rule_can_be() -> None:
    """A written day is one flowing step on a month, and no dry step at all."""
    assert flowing_steps(_days("1 d"), MONTH) == 1
    assert dry_steps(_days("1 d"), MONTH) == 0
    assert flowing_steps(_days("1 d"), nominal_step_days(7, "day")) == 1


def test_a_sub_daily_run_counts_a_written_day_in_hours() -> None:
    hour = nominal_step_days(1, "hour")

    assert flowing_steps(_days("1 d"), hour) == 24
    assert dry_steps(_days("1 d"), hour) == 24


def test_a_timestep_is_the_step_of_the_time_window_of_the_run() -> None:
    window = SimpleNamespace(step_value=2, step_unit="month")
    ctx = SimpleNamespace(setup=SimpleNamespace(time_grid=SimpleNamespace(window=window)))

    assert context_step_days(ctx) == pytest.approx(2 * MONTH)
    assert context_step_days(SimpleNamespace()) is None


# -- a stored run ------------------------------------------------------------


def _steps(extents) -> tuple[int, int]:
    return extents.maximal_flowing_steps, extents.minimal_dry_steps


def test_a_stored_monthly_run_counts_its_extents_in_its_own_timesteps() -> None:
    run = transient_run()

    assert run_step_days(run) == pytest.approx(MONTH)
    assert _steps(network_extents_from_run(run)) == (1, 1)
    assert _steps(network_extents_from_run(run, maximal_flowing_duration="5 months")) == (5, 1)
    assert _steps(network_extents_from_run(run, maximal_flowing_duration="45 d")) == (2, 1)
    assert _steps(network_extents_from_run(run, minimal_dry_duration="45 d")) == (1, 1)


def test_a_stored_run_that_sealed_no_timestep_is_refused_by_name() -> None:
    run = transient_run()
    run.config_snapshot = {"simulation": {"time": {}}}

    with pytest.raises(ValueError, match="sealed no timestep"):
        network_extents_from_run(run)


def test_a_rule_longer_than_the_year_is_refused_with_both_durations() -> None:
    with pytest.raises(ValueError, match="maximal_flowing_duration = '13 months'"):
        network_extents_from_run(transient_run(), maximal_flowing_duration="13 months")


def _sealed(extent: dict, *, step: dict | None = None) -> SimpleNamespace:
    time = {"step_value": 1, "step_unit": "month"} if step is None else step
    return SimpleNamespace(
        sim_id="sim-x",
        config_snapshot={
            "simulation": {"time": time},
            "calibration": {
                "outputs": {
                    "net": {
                        "support": "network",
                        "observed_network": "data.hydrography",
                        "extent": extent,
                    }
                }
            },
        },
    )


def test_the_redraw_reads_the_durations_a_run_sealed() -> None:
    settings = network_criterion_settings(
        _sealed({"maximal_flowing_duration": "30 d", "minimal_dry_duration": "1 month"})
    )

    assert settings.extent_rules.maximal_flowing_duration == "30 d"
    assert settings.extent_rules.minimal_dry_duration == "1 month"


def test_the_redraw_reads_the_counts_a_run_sealed_before_as_durations() -> None:
    settings = network_criterion_settings(
        _sealed({"maximal_flowing_steps": 2, "minimal_dry_steps": 1, "year_quorum": 1.0})
    )

    assert settings.extent_rules.maximal_flowing_duration == "2 months"
    assert settings.extent_rules.minimal_dry_duration == "1 month"
    assert settings.extent_rules.year_quorum == 1.0


def test_the_redraw_does_not_touch_the_snapshot_it_reads() -> None:
    run = _sealed({"maximal_flowing_steps": 2})

    network_criterion_settings(run)

    assert run.config_snapshot["calibration"]["outputs"]["net"]["extent"] == {
        "maximal_flowing_steps": 2
    }


# -- the doctor --------------------------------------------------------------

OLD_FILE = """\
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[calibration.outputs.seepage_network]
support = "network"
observed_network = "data.hydrography"

[calibration.outputs.seepage_network.extent]
maximal_flowing_steps = 2  # two months at least
minimal_dry_steps = 1
year_quorum = 1.0

[display.overrides.network_extent_bounds_map]
maximal_flowing_steps = 3

[[calibration.phases]]
name = "K"
parameters = ["K"]

[calibration.phases.overrides]
"display.overrides.network_extent_bounds_map.minimal_dry_steps" = 0
"""


def test_the_doctor_writes_the_count_as_that_many_steps_of_the_time_window(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(OLD_FILE, encoding="utf-8")

    changes = fix_config_file(path)

    written = path.read_text(encoding="utf-8")
    document = tomllib.loads(written)
    extent = document["calibration"]["outputs"]["seepage_network"]["extent"]
    assert extent == {
        "maximal_flowing_duration": "2 months",
        "minimal_dry_duration": "1 month",
        "year_quorum": 1.0,
    }
    assert document["display"]["overrides"]["network_extent_bounds_map"] == {
        "maximal_flowing_duration": "3 months"
    }
    overrides = document["calibration"]["phases"][0]["overrides"]
    assert overrides == {
        "display.overrides.network_extent_bounds_map.minimal_dry_duration": "0 months"
    }
    assert "# two months at least" in written
    assert not re.search(r"_steps\b", written)
    assert len(changes) == 4
    assert fix_config_file(path) == []


def test_the_doctor_writes_a_daily_count_in_days_and_an_hourly_one_in_hours(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[simulation.time]\nstep_value = "7 days"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\nminimal_dry_steps = 1\n",
        encoding="utf-8",
    )

    fix_config_file(path)

    extent = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["outputs"]["net"]
    assert extent["extent"] == {
        "maximal_flowing_duration": "21 days",
        "minimal_dry_duration": "7 days",
    }
    assert flowing_steps(_days("21 days"), nominal_step_days(7, "day")) == 3
    assert dry_steps(_days("7 days"), nominal_step_days(7, "day")) == 1


def test_the_doctor_leaves_a_count_whose_timestep_the_file_does_not_hold(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        'base_config = "project.toml"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert len(changes) == 1
    assert "maximal_flowing_steps left: the timestep is not in this file" in changes[0]
    assert "write the duration, such as '1 month'" in changes[0]
    assert "maximal_flowing_steps = 3" in path.read_text(encoding="utf-8")


def test_the_doctor_leaves_a_count_when_a_phase_sets_the_timestep(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[simulation.time]\nstep_value = "1 month"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\n"
        '[[calibration.phases]]\nname = "a"\n'
        '[calibration.phases.overrides]\n"simulation.time.step_value" = 7\n',
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert len(changes) == 1
    assert "a phase overrides the timestep" in changes[0]


def test_the_doctor_leaves_a_rule_written_under_both_names(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[simulation.time]\nstep_value = "1 month"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\n"
        'maximal_flowing_duration = "2 months"\n',
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert changes == [
        "calibration.outputs.net.extent.maximal_flowing_steps left: "
        "'maximal_flowing_duration' is given too, keep one"
    ]


# -- a sealed run ------------------------------------------------------------


def test_a_sealed_document_reads_the_old_counts_as_durations() -> None:
    doc = {
        "simulation": {"time": {"step_value": 1, "step_unit": "month"}},
        "calibration": {
            "outputs": {
                "net": {"support": "network", "extent": {"maximal_flowing_steps": 2}},
            }
        },
        "display": {"overrides": {"network_extent_bounds_map": {"minimal_dry_steps": 1}}},
    }

    migrate_sealed_config_doc(doc)

    assert doc["calibration"]["outputs"]["net"]["extent"] == {
        "maximal_flowing_duration": "2 months"
    }
    assert doc["display"]["overrides"]["network_extent_bounds_map"] == {
        "minimal_dry_duration": "1 month"
    }


def test_a_sealed_count_with_no_timestep_is_dropped_so_the_run_still_reads() -> None:
    doc = {
        "calibration": {
            "outputs": {"net": {"support": "network", "extent": {"minimal_dry_steps": 1}}}
        }
    }

    changes = migrate_sealed_config_doc(doc)

    assert doc["calibration"]["outputs"]["net"]["extent"] == {}
    assert any("minimal_dry_steps dropped (sealed)" in change for change in changes)


def test_a_frozen_run_with_the_old_counts_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        PROJECT.replace(
            'stream_geometry_path = "nancon_stream_network.gpkg"\n',
            'stream_geometry_path = "nancon_stream_network.gpkg"\n'
            "[calibration.outputs.seepage_network.extent]\n"
            'maximal_flowing_duration = "2 months"\nminimal_dry_duration = "1 month"\n',
        ),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(toml)
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = re.sub(
        r"^maximal_flowing_duration = .*$", "maximal_flowing_steps = 2", frozen, flags=re.M
    )
    old = re.sub(r"^minimal_dry_duration = .*$", "minimal_dry_steps = 1", old, flags=re.M)
    assert old != frozen
    assert "_duration" not in old
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    replayed = HydroModPyConfig.from_toml(sealed)

    extent = replayed.calibration.outputs["seepage_network"].extent
    assert (extent.maximal_flowing_duration, extent.minimal_dry_duration) == (
        "2 months",
        "1 month",
    )


# -- the figure --------------------------------------------------------------


def test_the_figure_takes_the_durations_and_refuses_the_old_counts() -> None:
    from hydromodpy.display.config import DisplayConfig

    DisplayConfig(
        overrides={
            "network_extent_bounds_map": {
                "maximal_flowing_duration": "5 months",
                "minimal_dry_duration": "0 d",
            }
        }
    )
    with pytest.raises(ValidationError, match="has no option 'maximal_flowing_steps'") as refused:
        DisplayConfig(overrides={"network_extent_bounds_map": {"maximal_flowing_steps": 5}})

    assert "maximal_flowing_duration" in str(refused.value)


def test_the_note_of_the_figure_says_the_duration_and_the_timesteps_it_made() -> None:
    from hydromodpy.display.figures.network_extent_bounds_map import extents_from_run

    run = transient_run()
    settings = network_criterion_settings(run)

    extents = extents_from_run(
        run, settings, maximal_flowing_duration="45 d", minimal_dry_duration="1 month"
    )

    assert (extents.maximal_flowing_duration, extents.maximal_flowing_steps) == ("45 d", 2)
    assert (extents.minimal_dry_duration, extents.minimal_dry_steps) == ("1 month", 1)
