from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProbeProtocol(Protocol):
    """Structural contract for a Validity Frame probe.

    A probe is a lightweight adapter around an external model or runtime source.
    The collector only relies on the methods below if they are present.

    Required:
    - role() -> str: returns the probe category (for example 'solver').

    Optional lifecycle hooks are supported by :class:`BaseProbe`, but are not
    part of the structural contract so that lightweight adapters can remain
    duck-typed with only the minimal surface.

    The returned payloads should be JSON-serializable or dataclasses that can be
    converted to JSON before persistence.
    """

    def role(self) -> str: ...

    def collect(self, source: Any = None) -> Any: ...


class BaseProbe(ABC):
    """Base class for a Validity Frame probe.

    Use this class when you want an explicit inheritance-based adapter.
    For static typing or duck-typed integration, see :class:`ProbeProtocol`.

    The collector only requires :meth:`role` and then calls optional lifecycle
    hooks when they are available.
    """

    @abstractmethod
    def role(self) -> str:
        """Return the probe role identifier.

        Typical values are ``system``, ``hardware``, ``runtime`` or ``solver``.
        """

    # Optional lifecycle hooks
    def collect(self, source: Any = None) -> Any:  # pragma: no cover - optional
        raise NotImplementedError

    def collect_start(self, start_time: float) -> Any:  # pragma: no cover - optional
        raise NotImplementedError

    def collect_end(self, start_time: float) -> Any:  # pragma: no cover - optional
        raise NotImplementedError
