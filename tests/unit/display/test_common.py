from __future__ import annotations

import builtins
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest

from hydromodpy.analysis.display.common import (
    make_figure,
    resolve_artifact_figure_dir,
    resolve_model_figure_dir,
)


def test_make_figure_matplotlib_fallback_accepts_ultraplot_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _patched_import(name, *args, **kwargs):
        if name == "ultraplot":
            raise ImportError("forced for fallback coverage")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched_import)

    fig, axs = make_figure(
        nrows=3,
        ncols=1,
        figsize=(4.0, 6.0),
        dpi=120,
        sharex=3,
        hspace=2.0,
    )
    try:
        axes = list(np.asarray(axs).flat)
        assert len(axes) == 3
        assert axes[0].get_shared_x_axes().joined(axes[0], axes[1])
        assert fig.subplotpars.hspace == pytest.approx(2.0)
    finally:
        plt.close(fig)


def test_resolve_artifact_figure_dir_uses_canonical_identifier() -> None:
    workspace = type("Workspace", (), {"simulations_folder": Path("simulations")})()

    path = resolve_artifact_figure_dir(workspace, "flow_main")

    assert path == Path("simulations") / "flow_main" / "_postprocess" / "_figures"


def test_resolve_model_figure_dir_is_deprecated_alias() -> None:
    workspace = type("Workspace", (), {"simulations_folder": Path("simulations")})()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        path = resolve_model_figure_dir(workspace, "flow_main")

    assert path == resolve_artifact_figure_dir(workspace, "flow_main")
    assert len(caught) == 1
    assert "deprecated" in str(caught[0].message)
