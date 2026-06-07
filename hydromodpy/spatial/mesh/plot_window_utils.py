"""Best-effort helpers for sizing Matplotlib GUI windows."""

from __future__ import annotations


def _call_noargs(obj, method_name: str):
    method = getattr(obj, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def maximize_figure_window(fig) -> None:
    """Best-effort maximize/resize for one Matplotlib figure window."""
    manager = getattr(getattr(fig, "canvas", None), "manager", None)
    if manager is None:
        return

    window = getattr(manager, "window", None)
    if window is not None:
        shown = False
        show_maximized = getattr(window, "showMaximized", None)
        if callable(show_maximized):
            try:
                show_maximized()
                return
            except Exception:
                pass

        state = getattr(window, "state", None)
        if callable(state):
            try:
                state("zoomed")
                return
            except Exception:
                pass

        wm_state = getattr(window, "wm_state", None)
        if callable(wm_state):
            try:
                wm_state("zoomed")
                return
            except Exception:
                pass

        width = _call_noargs(window, "winfo_screenwidth")
        height = _call_noargs(window, "winfo_screenheight")
        if width is not None and height is not None:
            geometry = getattr(window, "geometry", None)
            if callable(geometry):
                try:
                    geometry(f"{int(width)}x{int(height)}+0+0")
                    shown = True
                except Exception:
                    shown = False
            if shown:
                return
            resize = getattr(window, "resize", None)
            if callable(resize):
                try:
                    resize(int(width), int(height))
                    return
                except Exception:
                    pass

    frame = getattr(manager, "frame", None)
    if frame is not None:
        maximize = getattr(frame, "Maximize", None)
        if callable(maximize):
            try:
                maximize(True)
                return
            except Exception:
                pass

    full_screen_toggle = getattr(manager, "full_screen_toggle", None)
    if callable(full_screen_toggle):
        try:
            full_screen_toggle()
        except Exception:
            pass


def maximize_figure_windows(*figures) -> None:
    """Best-effort maximize/resize for one or many Matplotlib figures."""
    for fig in figures:
        if fig is None:
            continue
        maximize_figure_window(fig)
