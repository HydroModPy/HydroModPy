"""One registry engine, shared by every ``id -> class`` plugin surface.

The evaluator, forward-model, terrain-engine and mesh-engine registries resolve ``id -> class`` the same way: an in-tree declaration
imported on first lookup, then one scan of an entry-point group for the
out-of-tree surface. Only the noun, the id attribute, the group and the port
members differ, so they are parameters of :class:`PluginRegistry`.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from importlib.metadata import entry_points

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def _name_of(candidate: object) -> str:
    return str(getattr(candidate, "__qualname__", candidate))


class PluginRegistry:
    """Resolve an id to a class, from an in-tree declaration or an entry point.

    Parameters
    ----------
    kind
        The noun used in messages, for example ``"forward model"``.
    id_attribute
        The class attribute holding the id, read off the class and never passed in.
    group
        The entry-point group of the out-of-tree plugins.
    builtin_paths
        ``id -> "module:Class"`` of the in-tree classes, imported on first lookup.
    members
        Returns the port members a class must carry.
    default_id
        The id a ``None`` name resolves to.
    error
        The exception class raised for an unknown id, a class that cannot be loaded and
        a constructor that cannot be filled.
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
        id_attribute: str,
        group: str,
        builtin_paths: dict[str, str],
        members: Callable[[], tuple[str, ...]],
        default_id: str,
        error: type[Exception],
        validate: Callable[[type], None] | None = None,
        construction_options: tuple[str, ...] | None = None,
    ) -> None:
        self.kind = kind
        self.id_attribute = id_attribute
        self.group = group
        self.builtin_paths = builtin_paths
        self.members = members
        self.default_id = default_id
        self.error = error
        self.validate = validate
        self.construction_options = construction_options
        self.classes: dict[str, type] = {}
        self.plugins_loaded = False

    def builtin_ids(self) -> tuple[str, ...]:
        """Return the ids this build ships, sorted, plugins excluded."""
        return tuple(sorted(self.builtin_paths))

    def list_ids(self) -> tuple[str, ...]:
        """Return every id resolvable here, built-in and installed, sorted.

        Loads the plugin group, because the answer is wrong without it. Does not
        import a built-in: the path is the declaration, and the class behind one
        is only needed when somebody asks for it by name.
        """
        if not self.plugins_loaded:
            self.load_plugins()
        return tuple(sorted(set(self.classes) | set(self.builtin_paths)))

    def is_registered(self, name: str) -> bool:
        """Whether :meth:`get` would resolve *name* without raising."""
        return name in self.list_ids()

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
        class_id = getattr(cls, self.id_attribute, None)
        if not isinstance(class_id, str) or not class_id.strip():
            raise TypeError(
                f"{_name_of(cls)!r} declares {self.id_attribute}={class_id!r} on the class, "
                f"and a registry keyed on a name cannot hold a {self.kind} that has none. It "
                "is a ClassVar[str] in the port; a value computed per instance is not "
                "readable here."
            )
        # Wider than presence: a member bound to ``None`` passes ``hasattr`` and
        # fails the first call, so the registry is where it has to be refused.
        missing = tuple(name for name in self.members() if getattr(cls, name, None) is None)
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

    def get(self, name: str | None = None) -> type:
        """Return the class registered under *name*, or the default for ``None``.

        Resolution order is the cache, then the in-tree declaration, then one
        scan of the plugin group.

        Raises
        ------
        self.error
            When nothing answers to that name.
        """
        wanted = self.default_id if name is None else name
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

    def resolve_id(self, name: str | None = None) -> str:
        """Return the id the class behind *name* declares for itself.

        ``None`` and the default's own spelling resolve to one answer, which is
        what lets a record, a cache key or a report say what ran without
        depending on whether the document named it.
        """
        return str(getattr(self.get(name), self.id_attribute))

    def create(self, name: str | None = None, /, **options: object) -> object:
        """Build the class registered under *name*, binding the parameters it names.

        Only the constructor parameters the class declares are bound, keyword-only
        and positional-or-keyword alike. An option no parameter names never
        arrives, so the caller does not have to know what each class wants.

        Raises
        ------
        self.error
            From :meth:`get`; or when the constructor takes an argument
            positionally only, which a keyword cannot fill; or, when
            ``construction_options`` is set, a required one nothing serves.
        """
        cls = self.get(name)
        parameters = inspect.signature(cls).parameters
        label = getattr(cls, self.id_attribute, cls)
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

        Returns the number newly registered. A bad entry point is skipped with a
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
            declared_id = getattr(cls, self.id_attribute, None)
            if declared_id != name:
                logger.warning(
                    "%s plugin %r ignored: the entry-point name is %r while the class "
                    "declares %s=%r. The name is what a document writes and the id is what a "
                    "session is stamped with; two words for one %s is how the two start "
                    "describing different things.",
                    self.kind,
                    entry_point,
                    name,
                    self.id_attribute,
                    declared_id,
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

    def unregister(self, name: str) -> None:
        """Drop one entry, built-in declaration included. Primarily for tests.

        The declaration goes too, otherwise the next :meth:`get` lazy-loads the
        built-in straight back and the removal looks like it did nothing. A
        fixture that removes a built-in restores both mappings.
        """
        self.classes.pop(name, None)
        self.builtin_paths.pop(name, None)

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
        return self.register(cls, replace=True)
