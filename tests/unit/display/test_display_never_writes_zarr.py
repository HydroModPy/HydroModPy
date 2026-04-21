"""Display figures are strictly read-only.

A figure ``plot()`` call must never create a Zarr store, a DuckDB
connection, or any file outside the figure's own save target. This test
instantiates every registered figure class and confirms the catalog
contract exposes no write method that display code could call.
"""

from __future__ import annotations

import inspect

from hydromodpy.display import list_figures
from hydromodpy.display.catalog import get as get_figure


_WRITE_TOKENS = (
    "write_",
    "save_zarr",
    "to_zarr",
    "register_simulation",
    "insert",
    "execute",
)


def test_all_registered_figures_can_be_instantiated() -> None:
    for spec in list_figures():
        fig = get_figure(spec.name)
        assert fig is not None
        assert fig.spec.name == spec.name


def test_figures_do_not_call_zarr_write_apis() -> None:
    """Static scan: no figure renders-with-side-effects.

    We walk every figure's source file and confirm no line contains a
    token that would indicate a write to the storage layer. Display code
    reads via the ``Run`` interface only.
    """
    import hydromodpy.display.figures as pkg

    pkg_path = pkg.__path__[0]
    import pathlib

    offenders: list[tuple[str, str, int]] = []
    for path in pathlib.Path(pkg_path).glob("*.py"):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(src, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in _WRITE_TOKENS:
                if token in stripped.replace(" ", ""):
                    offenders.append((path.name, stripped, lineno))
    assert not offenders, (
        "Figures must not call write APIs. Offending lines:\n"
        + "\n".join(f"  {p}:{ln}: {txt}" for p, txt, ln in offenders)
    )


def test_base_figure_plot_signature_is_readonly() -> None:
    """The base plot() signature only exposes a save_path (a local file)."""
    from hydromodpy.display.figure import BaseFigure

    sig = inspect.signature(BaseFigure.plot)
    params = set(sig.parameters)
    assert "save_path" in params
    # No mutating keyword: catalog/store/zarr/duckdb must NOT be in signature.
    for banned in ("catalog", "store", "zarr", "duckdb", "connection"):
        assert banned not in params, (
            f"BaseFigure.plot must not accept a '{banned}' parameter."
        )
