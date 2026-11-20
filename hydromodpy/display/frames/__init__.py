"""Frames: one module per frame, named as its key of ``request.FRAMES``.

A frame module reads from top to bottom and holds three things.

``data(subject, panel) -> <Frame>Data`` reads through ``display.subject`` only,
converts to the display unit through ``display.variables``, and returns a frozen
dataclass whose ``table`` is a plain pandas DataFrame. ``figure(..., data=True)`` hands that
table to a user, and a test compares its numbers. ``panel`` is a resolved
``PanelRequest``: ``type`` set, holes filled, and for a map one variable and one
instant, since ``render`` splits small multiples before it calls ``data``.

``draw(ax, data, theme)`` draws the dataclass on one matplotlib axes with the
template of ``display.static``. It reads no subject, so the same numbers always
draw the same picture.

``draw_interactive(data, theme)`` is optional and returns a plotly figure. Only
the frames that hold it accept the interactive engine.

The overlays of a panel are drawn by ``render`` after ``draw``, since they read the
subject. The default overlays and the registry shapes a frame is the natural
frame of are written in ``request.FRAMES``.
"""
