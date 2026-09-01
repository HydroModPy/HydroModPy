"""``rectify_on_mesh`` requires a conditioned mesh top, and says so on load.

The rectified channel is traced by steepest descent on the mesh top. On an
unconditioned top that descent walks the pits the DEM-to-Voronoi projection puts
back, so the traced channel leaves the thalweg without a word. The refusal fires
where the user's TOML is read and nowhere else: a frozen run config must keep
replaying, faults included, or ``hmp run --resume`` would strand it.
"""

from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError


def _toml(project_root, *, rectify: bool, condition_top: bool, route: bool = False) -> str:
    return f"""
[workflow]
mode = "simulation"

[workspace]
project_root = "{project_root.as_posix()}"

[geographic]
source_mode = "synthetic"

[modflow6.sgrid]
condition_top = {str(condition_top).lower()}

[flow]
active_bc = ["sfr"]

[flow.sinks_sources.sfr.nancon]
stream_threshold_km2 = 1.5
rectify_on_mesh = {str(rectify).lower()}
route_drainage = {str(route).lower()}

[flow.sinks_sources.sfr.nancon.width]
kind = "constant"
value = "2 m"
"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_rectify_without_a_conditioned_top_is_refused(tmp_path):
    path = _write(
        tmp_path / "project.toml",
        _toml(tmp_path, rectify=True, condition_top=False),
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(path)

    message = str(excinfo.value)
    # Both halves of the fix must be named: the offending key in full, and the
    # flag to flip, so the user never has to guess which of the two to change.
    assert "flow.sinks_sources.sfr.nancon.rectify_on_mesh" in message
    assert "[modflow6.sgrid] condition_top" in message
    assert str(path) in message
    assert excinfo.value.code == "HMPY.E101"


def test_a_conditioned_top_is_accepted(tmp_path):
    path = _write(
        tmp_path / "project.toml",
        _toml(tmp_path, rectify=True, condition_top=True),
    )

    assert HydroModPyConfig.from_toml(path) is not None


def test_route_drainage_alone_is_not_gated(tmp_path):
    # A cell whose descent dead-ends under route_drainage simply stays a plain
    # DRN, which the drainage builder documents and handles. Refusing here would
    # break configs that turn condition_top off for a stated reason.
    path = _write(
        tmp_path / "project.toml",
        _toml(tmp_path, rectify=False, condition_top=False, route=True),
    )

    assert HydroModPyConfig.from_toml(path) is not None


class TestFrozenRunConfigsKeepReplaying:
    """The exemption is keyed on the run DIRECTORY, never on the filename."""

    def test_a_frozen_run_config_still_loads(self, tmp_path):
        path = _write(
            tmp_path / "runs" / "nancon_sfr_smoke" / "config.toml",
            _toml(tmp_path, rectify=True, condition_top=False),
        )

        assert HydroModPyConfig.from_toml(path) is not None

    def test_the_effective_overlay_beside_it_also_loads(self, tmp_path):
        # hmp run writes ".<stem>.effective.<hex>.toml" next to the frozen config
        # when --set / --overlay / HMP_SET_* apply, and THAT is the file resume
        # hands to from_toml. Keying the exemption on the name would refuse it.
        path = _write(
            tmp_path / "runs" / "nancon_sfr_smoke" / ".config.effective.a1b2c3.toml",
            _toml(tmp_path, rectify=True, condition_top=False),
        )

        assert HydroModPyConfig.from_toml(path) is not None

    def test_a_toml_merely_named_config_is_still_refused(self, tmp_path):
        path = _write(
            tmp_path / "configs" / "config.toml",
            _toml(tmp_path, rectify=True, condition_top=False),
        )

        with pytest.raises(ConfigValidationError):
            HydroModPyConfig.from_toml(path)
