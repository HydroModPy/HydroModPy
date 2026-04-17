from __future__ import annotations

import builtins

import matplotlib.pyplot as plt
import numpy as np
import pytest

from hydromodpy.analysis.display.common import make_figure


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
