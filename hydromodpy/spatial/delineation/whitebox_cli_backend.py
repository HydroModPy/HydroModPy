"""WhiteboxTools CLI-based delineation backend.

This module provides the slot for a delineation backend driven by the
``whitebox`` (formerly ``whitebox_tools``) Python bindings, which shell
out to the WhiteboxTools native CLI executable.

Status
------
The historical CLI adapter (``WhiteboxToolsBackend``) has been removed in
favour of the in-process :class:`WhiteboxWorkflowsBackend`. This module
is kept as a named placeholder so that the registry can surface a
predictable error when a caller explicitly asks for the CLI flavour. It
will be materialised again if future code needs to bypass the workflows
Python bindings (e.g. running against a pre-installed native CLI without
the ``whitebox_workflows`` wheel).
"""

from __future__ import annotations

from typing import Any


class WhiteboxCliBackend:
    """Placeholder for a future WhiteboxTools CLI-backed delineation backend.

    Implements :class:`hydromodpy.spatial.delineation.base.DelineationBackend`
    by raising :class:`NotImplementedError`. The registry returns this
    class only when explicitly requested.
    """

    name = "whitebox_cli"

    def __init__(self) -> None:
        raise NotImplementedError(
            "The WhiteboxTools CLI backend is not implemented. "
            "Use 'whitebox_workflows' (default) or 'synthetic' instead."
        )

    def flow_accumulation(self, dem: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def flow_direction(self, dem: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def stream_network(self, dem: Any, threshold: float, **kwargs: Any) -> Any:
        raise NotImplementedError

    def catchment_from_outlet(
        self, dem: Any, x: float, y: float, **kwargs: Any
    ) -> Any:
        raise NotImplementedError
