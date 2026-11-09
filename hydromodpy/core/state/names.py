"""The rule of a project name and of a run name, written once.

A name is the name of a folder: ``runs/<name>`` or the project folder. It holds
lower case letters, digits, ``_`` and ``-``, forty characters at most, no
doubled ``_``, and is not a name Windows reserves for a device. The trash writes
``/`` as ``__``, so a doubled ``_`` would read back as a path. A run name may end with its version,
``.v<N>``, which the forty characters do not count. Lower case keeps two names
apart on a disk that ignores case, and a refusal beats a cut, because two long
names with one prefix would fall into one folder.

:func:`check_name` refuses a name a person wrote that breaks the rule, with a
sentence that proposes the folded name. :func:`fold_name` folds a text the code
made into a name (a case of a plan, a file stem); the caller then passes the
result through :func:`check_name`, which still refuses it when it is too long
or reserved.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Literal

from hydromodpy.core.exceptions import ConfigError

MAX_NAME_LENGTH: Final[int] = 40
"""The longest name, without the ``.v<N>`` of a run version."""

RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
"""The device names Windows refuses as a folder name, alone or before a dot."""

NameKind = Literal["run", "project"]
"""What a name names: a run folder or a project folder."""

_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9_-]+")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<stem>.+)\.v(?P<n>[1-9][0-9]*)$")
_OUTSIDE_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9_-]+")
_UNDERSCORES_RE: Final[re.Pattern[str]] = re.compile(r"_+")


def fold_name(text: str) -> str:
    """Return *text* folded into the letters of a name.

    Accents are dropped, letters go to lower case, every run of other characters
    becomes one ``_``, and ``_`` or ``-`` at either end is removed. The result may
    be empty, too long or reserved: :func:`check_name` says so.
    """
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    folded = _OUTSIDE_RE.sub("_", ascii_text.strip().lower())
    return _UNDERSCORES_RE.sub("_", folded).strip("_-")


def check_name(name: str, *, what: NameKind) -> str:
    """Return *name* when it follows the rule of a *what* name, else refuse it.

    A run name may carry its version, ``baseline.v2``; the rule reads the stem.
    The refusal is a :class:`~hydromodpy.core.exceptions.ConfigError` (exit code
    14) whose sentence names the rule and proposes the folded name when there is
    one.
    """
    text = str(name)
    stem = text
    if what == "run":
        version = _VERSION_RE.match(text)
        if version is not None:
            stem = version.group("stem")
    if not stem:
        raise ConfigError(f"A {what} name cannot be empty. {_rule(what)}")
    if _NAME_RE.fullmatch(stem) is None:
        raise ConfigError(f"The {what} name {text!r} is refused. {_rule(what)}{_proposal(stem)}")
    if "__" in stem:
        raise ConfigError(
            f"The {what} name {text!r} holds a doubled underscore, which the trash uses to "
            f"write a path.{_proposal(stem)}"
        )
    if len(stem) > MAX_NAME_LENGTH:
        raise ConfigError(
            f"The {what} name {text!r} has {len(stem)} characters, and a {what} name keeps to "
            f"{MAX_NAME_LENGTH}. Write a shorter name."
        )
    if stem in RESERVED_NAMES:
        raise ConfigError(
            f"The {what} name {text!r} is a device name Windows reserves, and no folder takes "
            f"it there. Write another name, such as {stem + '_' + what!r}."
        )
    return text


def _rule(what: NameKind) -> str:
    """Return the sentence of the rule of a *what* name."""
    return (
        f"A {what} name holds lower case letters, digits, _ and -, "
        f"{MAX_NAME_LENGTH} characters at most."
    )


def _proposal(stem: str) -> str:
    """Return the sentence that proposes the folded *stem*, or nothing when none fits."""
    folded = fold_name(stem)
    if not folded or len(folded) > MAX_NAME_LENGTH or folded in RESERVED_NAMES:
        return ""
    return f" Write {folded!r}."


__all__ = ["MAX_NAME_LENGTH", "RESERVED_NAMES", "NameKind", "check_name", "fold_name"]
