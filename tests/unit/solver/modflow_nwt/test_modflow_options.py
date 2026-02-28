from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_nwt.modflow_options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)


def test_preprocess_options_normalize_cross_ylim_list():
    options = ModflowPreprocessOptions(cross_ylim=[10, 30], first_clim="MEAN")

    assert options.cross_ylim == (10.0, 30.0)
    assert options.first_clim == "mean"


def test_preprocess_options_accept_empty_cross_ylim_as_none():
    options = ModflowPreprocessOptions(cross_ylim=[])

    assert options.cross_ylim is None


def test_preprocess_options_reject_unknown_first_clim_keyword():
    with pytest.raises(ValueError, match="first_clim must be"):
        ModflowPreprocessOptions(first_clim="median")


def test_run_options_defaults_match_processing_signature():
    options = ModflowRunOptions()

    assert options.write_model is True
    assert options.run_model is False
    assert options.link_mt3dms is False
    assert options.verbose is True


def test_postprocess_options_defaults_are_stable():
    options = ModflowPostprocessOptions()

    assert options.watertable_elevation is True
    assert options.watertable_depth is True
    assert options.seepage_areas is True
    assert options.export_all_tif is False
