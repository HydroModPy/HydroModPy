"""One registry engine, shared by every ``id -> class`` plugin surface.

Each plugin surface is an instance of :class:`PluginRegistry`, exposed by its own
module: ``solvers`` and ``extractors`` in ``solver/base/registry.py``,
``data_sources`` in ``data/source/registry.py``, ``evaluators`` in
``calibration/evaluation/registry.py``, ``forward_models`` in
``calibration/evaluation/forward_registry.py``, ``mesh_engines`` in
``mesh/registry.py`` and ``terrain_engines`` in ``catchment/terrain/registry.py``.
They resolve a name the same way: an in-tree declaration imported on first
lookup, then one scan of an entry-point group for the out-of-tree surface. Only
the noun, the id attributes, the group and the port members differ, so they are
parameters here.

The contract of a registry is :meth:`~PluginRegistry.register`,
:meth:`~PluginRegistry.get` and :meth:`~PluginRegistry.names`.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from importlib.metadata import entry_points

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_MISSING = object()


def _name_of(candidate: object) -> str:
    return str(getattr(candidate, "__qualname__", candidate))


def _absent(cls: type, name: str) -> bool:
    """Whether *cls* has no member *name* of its own, or binds it to ``None``."""
    value = inspect.getattr_static(cls, name, _MISSING)
    return value is _MISSING or value is None


class PluginRegistry:
    """Resolve an id to a class, from an in-tree declaration or an entry point.

    An id is the values of ``id_attributes`` read off the class and joined by
    ``_``. A solver backend is keyed on ``("process_type", "name")``, so
    ``flow`` and ``modflow6`` give ``flow_modflow6``, which is also the name
    its entry point is published under. A name is compared with that join and
    never split, so a part that carries a ``_`` stays whole.

    Parameters
    ----------
    kind
        The noun used in messages, for example ``"forward model"``.
    id_attributes
        The class attributes whose values, joined by ``_``, make the id. They are
        read off the class and never passed in.
    group
        The entry-point group of the out-of-tree plugins.
    builtin_paths
        ``id -> "module:Class"`` of the in-tree classes, imported on first lookup.
    members
        Returns the port members a class must carry, neither absent nor ``None``.
    error
        The exception class raised for an unknown id, a class that cannot be loaded and
        a constructor that cannot be filled.
    default_id
        The id that a lookup without a name resolves to, or ``None`` when a name
        is always required.
    validate
        Called by :meth:`register` after the member check. It raises ``TypeError`` to
        refuse a class for a reason the member list cannot express.
    construction_options
        When set, :meth:`create` refuses a required parameter outside it, because
        nothing could fill it. When ``None``, the constructor is called as it is.
    """

    def __init__(
        self,
        *,
        kind: str,
        id_attributes: tuple[str, ...],
        group: str,
        builtin_paths: dict[str, str],
        members: Callable[[], tuple[str, ...]],
        error: type[Exception],
        default_id: str | None = None,
        validate: Callable[[type], None] | None = None,
        construction_options: tuple[str, ...] | None = None,
    ) -> None:
        if not id_attributes:
            raise ValueError(f"A {kind} registry needs at least one id attribute.")
        self.kind = kind
        self.id_attributes = id_attributes
        self.group = group
        self.builtin_paths = builtin_paths
        self.members = members
        self.error = error
        self.default_id = default_id
        self.validate = validate
        self.construction_options = construction_options
        self.classes: dict[str, type] = {}
        self.plugins_loaded = False

    def names(self, *prefix: str, shipped_only: bool = False) -> tuple[str, ...]:
        """Return the ids resolvable here, sorted, under *prefix* when one is given.

        With a prefix, an id is kept when it equals the joined prefix or starts
        with it followed by ``_``, and the prefix is stripped: ``names("flow")``
        gives ``modflow6`` for ``flow_modflow6``. An id equal to the prefix gives
        the empty string, so a full key answers whether it is registered.

        Loads the plugin group, because the answer is wrong without it, unless
        *shipped_only* asks for the ids this build ships. Does not import a
        built-in: the path is the declaration.
        """
        if shipped_only:
            ids = set(self.builtin_paths)
        else:
            if not self.plugins_loaded:
                self.load_plugins()
            ids = set(self.classes) | set(self.builtin_paths)
        if not prefix:
            return tuple(sorted(ids))
        joined = "_".join(prefix)
        return tuple(
            sorted(
                class_id[len(joined) + 1 :]
                for class_id in ids
                if class_id == joined or class_id.startswith(f"{joined}_")
            )
        )

    def register(self, cls: type, *, replace: bool = False) -> type:
        """Register a class under the id it declares, and return it unchanged.

        The id is read off the class and never passed in, so a session record and
        the document that asked for it cannot name different classes.

        Raises
        ------
        TypeError
            When the class declares no usable id, or lacks a port member.
        ValueError
            When the id is already taken and *replace* is not set.
        """
        class_id = self._declared_id(cls)
        if class_id is None:
            raise TypeError(
                f"{_name_of(cls)!r} declares {self._declaration(cls)} on the class, and a "
                f"registry keyed on a name cannot hold a {self.kind} that has none. Each "
                "is a non-empty ClassVar[str] in the port; a value computed per instance "
                "is not readable here."
            )
        # Wider than presence. A member bound to ``None`` passes ``hasattr`` and
        # fails the first call. A member only a metaclass ``__getattr__`` answers
        # is not on the class, and ``getattr_static`` does not ask the metaclass.
        missing = tuple(name for name in self.members() if _absent(cls, name))
        if missing:
            raise TypeError(
                f"{_name_of(cls)!r} cannot serve {class_id!r}: it does not satisfy the "
                f"{self.kind} port, missing or unusable {', '.join(missing)}. The gap would "
                "surface after the setup rather than here."
            )
        if self.validate is not None:
            self.validate(cls)
        # Both mappings, and two lookups compared against ``None``.
        #
        # The declarations and not only the imported classes, because an in-tree
        # id is a declaration until the first lookup imports it: before that
        # lookup it looks free, and a class could claim the default silently and
        # answer in place of the one this build ships.
        #
        # Two lookups rather than ``a or b``, because a class is truthy unless
        # its metaclass says otherwise, and one that said otherwise would read as
        # absent and be displaced by the next registration, on any id.
        taken: object | None = self.classes.get(class_id)
        if taken is None:
            taken = self.builtin_paths.get(class_id)
        if taken is not None and not replace:
            raise ValueError(
                f"A {self.kind} is already registered for {class_id!r}: {_name_of(taken)}. "
                "Pass replace=True to substitute it, which is a deliberate in-process "
                "substitution the cache key cannot see."
            )
        self.classes[class_id] = cls
        return cls

    def get(self, *parts: str | None) -> type:
        """Return the class registered under the id the *parts* join to.

        ``get("flow", "modflow6")`` and ``get("flow_modflow6")`` are the same
        lookup. No part, or a single ``None``, gives the default. Resolution
        order is the cache, then the in-tree declaration, then one scan of the
        plugin group.

        Raises
        ------
        self.error
            When nothing answers to that name, or no name is given and the
            registry has no default.
        """
        wanted = self._wanted(parts)
        cls = self.classes.get(wanted)
        if cls is not None:
            return cls
        cls = self._load_builtin(wanted)
        if cls is not None:
            return cls
        if not self.plugins_loaded:
            self.load_plugins()
            cls = self.classes.get(wanted)
            if cls is not None:
                return cls
        known = ", ".join(sorted(set(self.classes) | set(self.builtin_paths))) or "none"
        raise self.error(
            f"No {self.kind} is registered for {wanted!r}. This installation serves {known}. "
            f"A third-party {self.kind} joins that list through the {self.group!r} "
            "entry-point group, without a patch to HydroModPy."
        )

    def create(self, *parts: str | None, **options: object) -> object:
        """Build the class registered under *parts*, binding the parameters it names.

        Kept beside :meth:`get` because four ports build a plugin from named
        options, and only the registry knows which of them the class takes. Only
        the constructor parameters the class declares are bound, keyword-only
        and positional-or-keyword alike. An option no parameter names never
        arrives, so the caller does not have to know what each class wants.

        Raises
        ------
        self.error
            From :meth:`get`; or when the constructor takes an argument
            positionally only, which a keyword cannot fill; or, when
            ``construction_options`` is set, a required one nothing serves.
        """
        cls = self.get(*parts)
        parameters = inspect.signature(cls).parameters
        label = self._declared_id(cls) or _name_of(cls)
        positional_only = [
            parameter_name
            for parameter_name, parameter in parameters.items()
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
            and parameter.default is inspect.Parameter.empty
        ]
        if positional_only:
            raise self.error(
                f"{self.kind.capitalize()} {label!r} takes {', '.join(positional_only)} "
                "positionally only, and it is built from named options. Declare them as "
                "keyword parameters."
            )
        bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        if self.construction_options is not None:
            # Named here rather than left to the constructor: a TypeError out of
            # somebody else's __init__ says nothing about which vocabulary this
            # route speaks.
            unserved = [
                parameter_name
                for parameter_name, parameter in parameters.items()
                if parameter.kind in bindable
                and parameter.default is inspect.Parameter.empty
                and parameter_name not in options
            ]
            if unserved:
                raise self.error(
                    f"{self.kind.capitalize()} {label!r} demands {', '.join(unserved)}, and a "
                    f"{self.kind} is built from {', '.join(self.construction_options)}. What "
                    "it needs beyond those it reads from the configuration it is handed, or "
                    "gives a default."
                )
        arguments = {
            parameter_name: options[parameter_name]
            for parameter_name, parameter in parameters.items()
            if parameter.kind in bindable and parameter_name in options
        }
        return cls(**arguments)

    def load_plugins(self, *, force: bool = False) -> int:
        """Register every conforming class declared in the entry-point group.

        Kept public because :meth:`get` and :meth:`names` call it once, and a
        test that installs an entry point calls it again with *force*. Returns
        the number newly registered. A bad entry point is skipped with a
        warning naming what is wrong with it, never raised: one broken plugin
        must not take down a calibration that asked for a different one.
        """
        if self.plugins_loaded and not force:
            return 0

        count = 0
        try:
            declared = tuple(entry_points(group=self.group))
        except Exception as exc:
            # Deliberately the whole scan and not one entry point: unreadable or
            # contradictory distribution metadata takes down ``importlib.metadata``
            # for every group at once, and a run that asked for the built-in must
            # not be taken down by a distribution it never named.
            logger.warning(
                "the %r entry-point group could not be scanned, so no plugin is registered: %s",
                self.group,
                exc,
            )
            self.plugins_loaded = True
            return 0
        for entry_point in declared:
            name = str(entry_point.name).strip()
            if not name:
                logger.warning(
                    "%s plugin %r ignored: its entry-point name is empty.", self.kind, entry_point
                )
                continue
            if name in self.builtin_paths:
                logger.warning(
                    "%s plugin %r ignored: %r is a %s this build ships. Answering under that "
                    "name would make a calibration session record a method it did not run.",
                    self.kind,
                    entry_point,
                    name,
                    self.kind,
                )
                continue
            if name in self.classes and not force:
                continue
            try:
                cls = entry_point.load()
            except Exception as exc:  # pragma: no cover - exercised with stub entry points
                logger.warning("failed to load %s plugin %r: %s", self.kind, entry_point, exc)
                continue
            if self._declared_id(cls) != name:
                logger.warning(
                    "%s plugin %r ignored: the entry-point name is %r while the class "
                    "declares %s. The name is what a document writes and the id is what a "
                    "session is stamped with; two words for one %s is how the two start "
                    "describing different things.",
                    self.kind,
                    entry_point,
                    name,
                    self._declaration(cls),
                    self.kind,
                )
                continue
            try:
                self.register(cls, replace=force)
            except (TypeError, ValueError) as exc:
                logger.warning("%s plugin %r ignored: %s", self.kind, entry_point, exc)
                continue
            count += 1
        self.plugins_loaded = True
        return count

    def unregister(self, *parts: str) -> None:
        """Drop one entry, built-in declaration included.

        Kept for tests, which add a class for one case and take it back. The
        declaration goes too, otherwise the next :meth:`get` lazy-loads the
        built-in straight back and the removal looks like it did nothing. A
        fixture that removes a built-in restores both mappings.
        """
        name = "_".join(parts)
        self.classes.pop(name, None)
        self.builtin_paths.pop(name, None)

    def _wanted(self, parts: tuple[str | None, ...]) -> str:
        """The id *parts* join to, or the default for no part or a single ``None``."""
        if not parts or parts == (None,):
            if self.default_id is None:
                raise self.error(
                    f"A {self.kind} has no default here, so it is named. This installation "
                    f"serves {', '.join(self.names()) or 'none'}."
                )
            return self.default_id
        if not all(isinstance(part, str) for part in parts):
            raise self.error(f"A {self.kind} is named by strings, not by {parts!r}.")
        return "_".join(str(part) for part in parts)

    def _declared_id(self, cls: object) -> str | None:
        """The id *cls* declares, or ``None`` when one of its parts is not a non-empty string."""
        values = [getattr(cls, attribute, None) for attribute in self.id_attributes]
        if not all(isinstance(value, str) and value.strip() for value in values):
            return None
        return "_".join(str(value) for value in values)

    def _declaration(self, cls: object) -> str:
        """What *cls* declares for the id attributes, for a message."""
        values = ", ".join(repr(getattr(cls, attribute, None)) for attribute in self.id_attributes)
        return f"{', '.join(self.id_attributes)} = {values}"

    def _load_builtin(self, name: str) -> type | None:
        """Import and register the in-tree class for *name*, if there is one."""
        path = self.builtin_paths.get(name)
        if path is None:
            return None
        module_path, _, class_name = path.partition(":")
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
        except Exception as exc:
            # Deliberately every exception and not ``ImportError``: a module that
            # fails at import time fails in whatever way its own imports do.
            raise self.error(
                f"{name!r} is declared by this build at {path!r} and cannot be loaded here: "
                f"{type(exc).__name__}: {exc}. The declaration is right and the installation "
                "is not, so this is fixed by repairing the environment, not by editing the "
                "document."
            ) from exc
        if self._declared_id(cls) != name:
            raise self.error(
                f"{name!r} is declared by this build at {path!r}, and that class declares "
                f"{self._declaration(cls)}. The declaration and the class have to name the "
                f"same {self.kind}."
            )
        return self.register(cls, replace=True)
