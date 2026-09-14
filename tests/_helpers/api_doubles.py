"""Reusable context-manager doubles for the functional facade tests.

The ``hmp`` verbs open a ``Project`` or a ``Catalog`` as a context
manager and forward kwargs. These doubles record what they receive so a test
can assert the wiring without a real backend. Import them with an absolute
path: ``from tests._helpers.api_doubles import CapturingProject``.
"""

from __future__ import annotations

from typing import Any


def make_capturing_project(
    captured: dict[str, Any],
    *,
    result: Any,
    verb: str,
) -> type:
    """Build a Project double that records init args and the verb kwargs.

    ``captured`` collects ``init_cfg``, ``init_headless``, ``verb_kwargs`` and
    ``closed``. ``verb`` is the method name to expose (``simulate`` or
    ``calibrate``) returning ``result``.
    """

    class CapturingProject:
        def __init__(self, cfg: Any, *, headless: bool = True) -> None:
            captured["init_cfg"] = cfg
            captured["init_headless"] = headless

        def __enter__(self) -> CapturingProject:
            return self

        def __exit__(self, *exc: object) -> None:
            captured["closed"] = True

        def _verb(self, **kwargs: Any) -> Any:
            captured["verb_kwargs"] = kwargs
            return result

    setattr(CapturingProject, verb, CapturingProject._verb)
    return CapturingProject


def make_capturing_catalog(captured: dict[str, Any]) -> type:
    """Build a Catalog double recording ``workspace_root``.

    ``captured`` collects ``workspace_root`` (the constructor arg) and
    ``closed`` (set on context exit).
    """

    class CapturingCatalog:
        def __init__(self, workspace_root: Any) -> None:
            captured["workspace_root"] = workspace_root

        def __enter__(self) -> CapturingCatalog:
            return self

        def __exit__(self, *exc: object) -> None:
            captured["closed"] = True

    return CapturingCatalog


def make_capturing_index(captured: dict[str, Any]) -> type:
    """Build a GlobalIndex double recording ``db_path`` and ``read_only``."""

    class CapturingIndex:
        def __init__(self, db_path: Any, *, read_only: bool = False) -> None:
            captured["db_path"] = db_path
            captured["read_only"] = read_only

        def close(self) -> None:
            captured["closed"] = True

    return CapturingIndex
