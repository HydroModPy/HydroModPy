"""Interactive viewer stubs (bokeh/holoviews/panel).

These entry points are reserved for v2.x. The optional ``interactive``
extra installs the dependencies; the runtime helpers below explain how
to call them once a real implementation lands.

Example::

    pip install hydromodpy[interactive]

The actual Panel/Holoviews dashboards will plug into
``hmp.read(sim, "head", ...)`` and reuse the rasterization paths in
``hydromodpy.display.scalable``.
"""

from __future__ import annotations

from typing import Any


def panel_view(*args: Any, **kwargs: Any) -> Any:
    """Interactive Panel dashboard for one or more simulations.

    Reserved for v2.x. Raises :class:`NotImplementedError` today.
    """
    raise NotImplementedError(
        "Interactive panel ready-to-go in v2.x. "
        "Install the extra with `pip install hydromodpy[interactive]` when the feature lands."
    )


def hvplot_field(*args: Any, **kwargs: Any) -> Any:
    """Interactive ``hvplot`` rendering of a Run field.

    Reserved for v2.x. Raises :class:`NotImplementedError` today.
    """
    raise NotImplementedError(
        "hvplot_field is reserved for v2.x. "
        "Install the extra with `pip install hydromodpy[interactive]` when the feature lands."
    )


def bokeh_timeseries(*args: Any, **kwargs: Any) -> Any:
    """Interactive Bokeh time-series viewer.

    Reserved for v2.x. Raises :class:`NotImplementedError` today.
    """
    raise NotImplementedError(
        "bokeh_timeseries is reserved for v2.x. "
        "Install the extra with `pip install hydromodpy[interactive]` when the feature lands."
    )


__all__ = ["bokeh_timeseries", "hvplot_field", "panel_view"]
