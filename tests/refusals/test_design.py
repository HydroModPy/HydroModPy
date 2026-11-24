"""A [sites.design] plan refuses what would silently draw the wrong points, by name."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.project.launch.plan import (
    SitesProjectError,
    expand_plan,
    group_issues,
    write_plan_draft,
)
from tests.unit.project.launch.test_plan import _K_PATH, _seal
from tests.unit.project.launch.test_plan_design import _design, _expand, _project, _rewrite


def test_sealed_points_that_move_are_refused(tmp_path: Path) -> None:
    project = _project(tmp_path, _design("lhs", "n = [4]"))
    draft = _expand(project)
    write_plan_draft(project, draft)
    case = next(c for c in draft.cases if c.case_id == "nancon-b1p0001")
    _seal(project, case.case_id, case.config_hash)
    _rewrite(project, "n = [4]", "n = [6]")

    with pytest.raises(SitesProjectError, match="list of lots"):
        _expand(project)


REFUSALS = [
    ("seed_missing", lambda p: _rewrite(p, "seed = 3\n", ""), "seed is required"),
    ("n_missing", lambda p: _rewrite(p, "n = 4\n", ""), "n is required"),
    ("n_zero", lambda p: _rewrite(p, "n = 4", "n = 0"), "n is required and positive"),
    ("method", lambda p: _rewrite(p, 'method = "sobol"', 'method = "maximin"'), "sobol, lhs, grid"),
    ("normal", lambda p: _rewrite(p, 'sampling = "log_uniform"', 'sampling = "normal"'), "normal"),
    (
        "sampling_unwritten",
        lambda p: _rewrite(p, 'sampling = "log_uniform"\n', ""),
        "write sampling",
    ),
    ("bound_zero_log", lambda p: _rewrite(p, "[1e-7, 1e-3]", "[0, 1e-3]"), "strictly positive"),
    ("mode_scale", lambda p: _rewrite(p, 'path = "', 'mode = "scale"\npath = "'), "mode"),
    ("no_path", lambda p: _rewrite(p, f'path = "{_K_PATH}"\n', ""), "write path"),
    (
        "option_of_another_method",
        lambda p: _rewrite(
            p, 'recipe = "base"', 'recipe = "base"\noptions = { optimization = "random-cd" }'
        ),
        "belongs to lhs",
    ),
    (
        "n_samples_option",
        lambda p: _rewrite(p, 'recipe = "base"', 'recipe = "base"\noptions = { n_samples = 4 }'),
        "written n",
    ),
    ("no_recipe_among_several", lambda p: _rewrite(p, 'recipe = "base"\n', ""), "Name the one"),
    (
        "recipe_unknown",
        lambda p: _rewrite(p, 'recipe = "base"', 'recipe = "nope"'),
        "not declared",
    ),
    (
        "also_bound",
        lambda p: _rewrite(p, "[sites.bind]\n", f'[sites.bind]\n"{_K_PATH}" = "gauge"\n'),
        "also bound",
    ),
    (
        "also_set_by_the_recipe",
        lambda p: _rewrite(
            p,
            'base = "project.toml"',
            f'base = {{ file = "project.toml", set = {{ "{_K_PATH}" = 1e-5 }} }}',
        ),
        "has one source",
    ),
    (
        "site_scoped_key",
        lambda p: _rewrite(p, f'path = "{_K_PATH}"', 'path = "geographic.catchment.x_outlet"'),
        "belongs to one catchment",
    ),
    (
        "unknown_key",
        lambda p: _rewrite(p, f'path = "{_K_PATH}"', 'path = "flow.nope.value"'),
        "hmp config targets",
    ),
    (
        "calibration_in_base",
        lambda p: (p / "project.toml").write_text(
            (p / "project.toml").read_text(encoding="utf-8") + '\n[calibration]\nmethod = "lhs"\n',
            encoding="utf-8",
        ),
        "calibration",
    ),
]


@pytest.mark.parametrize(
    ("change", "fragment"), [r[1:] for r in REFUSALS], ids=[r[0] for r in REFUSALS]
)
def test_design_refusals(tmp_path: Path, change, fragment: str) -> None:
    project = _project(tmp_path)
    change(project)

    with pytest.raises(Exception, match=fragment):
        draft = _expand(project)
        # A refusal of one case lands in the draft, one of the project raises.
        if not draft.ok:
            raise SitesProjectError("; ".join(group_issues(draft.errors)))


def test_set_on_a_drawn_key_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)

    with pytest.raises(SitesProjectError, match="overwrite every point"):
        expand_plan(
            project,
            project / "project.toml",
            set_overrides={"flow": {"param": {"K": {"field": {"value": 1e-5}}}}},
        )
    with pytest.raises(SitesProjectError, match="overwrite every point"):
        expand_plan(
            project, project / "project.toml", env={"HMP_SET_flow__param__K__field__value": "1e-5"}
        )


def test_a_parameter_named_like_a_site_column_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _rewrite(project, "parameters.K]", "parameters.gauge]")

    with pytest.raises(SitesProjectError, match="also a column of"):
        _expand(project)


@pytest.mark.parametrize(
    "layer",
    [
        {"flow": {"param": {"K": {"field": 1e-5}}}},
        {"flow": {"param": {"K": 1e-5}}},
    ],
    ids=["parent_table", "grandparent_table"],
)
def test_set_on_a_parent_table_of_a_drawn_key_is_refused(tmp_path: Path, layer: dict) -> None:
    project = _project(tmp_path)

    with pytest.raises(SitesProjectError, match="overwrite every point"):
        expand_plan(project, project / "project.toml", set_overrides=layer)


def test_a_site_override_on_a_drawn_key_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "site_overrides" / "nancon.toml").write_text(
        "[flow.param.K.field]\nvalue = 1e-5\n", encoding="utf-8"
    )

    with pytest.raises(SitesProjectError, match="site_overrides/nancon.toml"):
        _expand(project)


def test_a_recipe_bind_on_a_drawn_key_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "b.toml").write_text(
        f'base_config = "project.toml"\n[sites.bind]\n"{_K_PATH}" = "gauge"\n', encoding="utf-8"
    )
    _rewrite(project, 'base = "project.toml"', 'base = "b.toml"')

    with pytest.raises(SitesProjectError, match="binds .* in .sites.bind"):
        _expand(project)


def _sealed_lhs(tmp_path: Path) -> Path:
    project = _project(tmp_path, _design("lhs", "n = [4]"))
    draft = _expand(project)
    write_plan_draft(project, draft)
    case = next(c for c in draft.cases if c.case_id == "nancon-b1p0001")
    _seal(project, case.case_id, case.config_hash)
    return project


@pytest.mark.parametrize(
    ("old", "new"),
    [("bounds = [1e-7, 1e-3]", "bounds = [1e-8, 1e-3]"), ("seed = 3", "seed = 4")],
    ids=["new_bounds", "new_seed"],
)
def test_a_redesign_is_a_new_plan_not_a_refusal(tmp_path: Path, old: str, new: str) -> None:
    project = _sealed_lhs(tmp_path)
    _rewrite(project, old, new)

    assert _expand(project).ok
