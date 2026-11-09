"""What :class:`Bounds` permits, and what it refuses by name.

The refusals carry the sentence a reader acts on: the host or the path that
stepped out, the list the call honours, and the option that widens it. The
object is pickled to worker processes and frozen, so a trial cannot widen
its own call halfway through.
"""

from __future__ import annotations

import dataclasses
import pickle
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import BoundsError
from hydromodpy.core.runtime.bounds import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DEFAULT_TIMEOUT_S,
    Bounds,
)

GEO = "api.geosas.fr"
GEOPF = "data.geopf.fr"


# --------------------------------------------------------------------------- #
# permits_host
# --------------------------------------------------------------------------- #


def test_the_default_bounds_permit_every_host() -> None:
    """``None`` says nothing is named, which is the behaviour of a machine."""
    bounds = Bounds()
    assert bounds.permits_host(GEO)
    assert bounds.permits_host("localhost")
    assert bounds.permits_host("169.254.1.1")


def test_an_empty_set_of_hosts_declares_the_call_offline() -> None:
    bounds = Bounds(allowed_hosts=frozenset())
    assert not bounds.permits_host(GEO)
    assert not bounds.permits_host("localhost")


@pytest.mark.parametrize(
    ("allowed", "asked", "permitted"),
    [
        ((GEO,), GEO, True),
        (("API.GEOSAS.FR",), GEO, True),
        ((GEO,), "API.GEOSAS.FR", True),
        (("café.example.org",), "café.example.org", True),
        (("café.example.org",), "CAFE.example.org", False),
        ((GEOPF,), "api.geosas.fr", False),
        ((GEO,), "api.geosas.fr.evil.org", False),
        ((GEO,), "example.org:8443", False),
        ((GEO,), "api.geosas.fr:443", True),
    ],
    ids=[
        "listed",
        "listed-uppercase",
        "asked-uppercase",
        "idna-name",
        "idna-different-name",
        "other-host",
        "name-composed-with-a-host",
        "other-name-with-a-port",
        "port-removed",
    ],
)
def test_a_named_set_of_hosts_compares_the_name_exactly(
    allowed: tuple[str, ...], asked: str, permitted: bool
) -> None:
    """Lower case and IDNA make the spellings equal, and nothing else does.

    No glob: the eight shipped hosts are exact names, and a joker would widen
    a call without a caller asking for it.
    """
    bounds = Bounds(allowed_hosts=frozenset(allowed))
    assert bounds.permits_host(asked) is permitted


# --------------------------------------------------------------------------- #
# permits_path
# --------------------------------------------------------------------------- #


def test_the_default_bounds_limit_no_path() -> None:
    assert Bounds().permits_path("/any/where")


@pytest.mark.parametrize(
    ("below", "permitted"),
    [
        ("", True),
        ("child", True),
        ("child/grand-child", True),
        ("..", False),
        ("../other-place", False),
    ],
    ids=["the-root-itself", "under-the-root", "nested", "parent", "outside"],
)
def test_a_named_set_of_roots_bounds_the_paths_the_caller_names(
    tmp_path: Path, below: str, permitted: bool
) -> None:
    root = tmp_path / "roots" / "one"
    (root / "child" / "grand-child").mkdir(parents=True)
    bounds = Bounds(allowed_roots=(root,))
    path = root if below == "" else root / below
    assert bounds.permits_path(path) is permitted


def test_a_link_out_of_the_roots_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link = root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    bounds = Bounds(allowed_roots=(root,))
    assert bounds.permits_path(link) is False


def test_a_root_spelled_through_a_parent_resolves_once(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    nested = root / "one"
    nested.mkdir(parents=True, exist_ok=True)
    bounds = Bounds(allowed_roots=(root / ".." / "roots" / "one",))
    assert bounds.permits_path(nested)
    assert tuple(bounds.allowed_roots) == (nested.resolve(),)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_download_bytes": 0},
        {"max_download_bytes": -5},
        {"max_download_bytes": 1.5},
        {"max_download_bytes": True},
        {"timeout_s": 0},
        {"timeout_s": -0.5},
        {"timeout_s": "30"},
        {"allowed_hosts": {""}},
        {"allowed_hosts": {"   "}},
        {"allowed_hosts": {"http://api.geosas.fr"}},
        {"allowed_hosts": {"api.geosas.fr/hydro"}},
        {"allowed_roots": ("relative/one",)},
        {"allowed_roots": (3.5,)},
        {"allowed_roots": ("",)},
    ],
    ids=[
        "zero-bytes",
        "negative-bytes",
        "float-bytes",
        "bool-bytes",
        "zero-delay",
        "negative-delay",
        "string-delay",
        "empty-host",
        "blank-host",
        "host-with-a-scheme",
        "host-with-a-path",
        "relative-root",
        "root-not-a-path",
        "empty-root",
    ],
)
def test_the_constructor_refuses_what_it_cannot_mean(kwargs: dict) -> None:
    with pytest.raises(BoundsError):
        Bounds(**kwargs)


def test_the_defaults_are_the_ones_of_today() -> None:
    """2 GiB for one download, 30.0 s of delay, nothing bounded."""
    bounds = Bounds()
    assert bounds.max_download_bytes == DEFAULT_MAX_DOWNLOAD_BYTES == 2_147_483_648
    assert bounds.timeout_s == DEFAULT_TIMEOUT_S == 30.0
    assert bounds.allowed_hosts is None
    assert bounds.allowed_roots is None


# --------------------------------------------------------------------------- #
# The refusals, by name
# --------------------------------------------------------------------------- #


def test_require_host_names_the_host_the_list_and_the_option() -> None:
    bounds = Bounds(allowed_hosts=frozenset({GEOPF}))
    with pytest.raises(BoundsError) as raised:
        bounds.require_host(GEO, why="asking hydrometry_hubeau")
    message = str(raised.value)
    assert "asking hydrometry_hubeau" in message
    assert GEO in message
    assert GEOPF in message
    assert "--allow-host" in message
    assert "Bounds(allowed_hosts=...)" in message


def test_require_host_accepts_a_listed_host() -> None:
    bounds = Bounds(allowed_hosts=frozenset({GEO}))
    bounds.require_host("API.GEOSAS.FR", why="asking")
    bounds.require_host(f"{GEO}:443", why="asking")


def test_require_hosts_names_every_refused_host_at_once() -> None:
    bounds = Bounds(allowed_hosts=frozenset({GEOPF}))
    with pytest.raises(BoundsError) as raised:
        bounds.require_hosts((GEO, GEOPF, "overpass-api.de"), why="asking crossings_bdtopo")
    message = str(raised.value)
    assert "overpass-api.de" in message and GEO in message
    assert "crossings_bdtopo" in message


def test_require_hosts_passes_a_source_with_no_host() -> None:
    """A computed or local source declares none and is asked for anyway."""
    bounds = Bounds(allowed_hosts=frozenset())
    bounds.require_hosts((), why="asking recharge_synthetic")


def test_require_path_names_the_path_the_roots_and_the_argument(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    bounds = Bounds(allowed_roots=(root,))
    with pytest.raises(BoundsError) as raised:
        bounds.require_path(other / "exports", why="delivering a copy")
    message = str(raised.value)
    assert str(other / "exports") in message
    assert str(root) in message
    assert "Bounds(allowed_roots=...)" in message
    bounds.require_path(root, why="delivering a copy")


# --------------------------------------------------------------------------- #
# The object itself
# --------------------------------------------------------------------------- #


def test_a_bounds_is_frozen(tmp_path: Path) -> None:
    bounds = Bounds(allowed_hosts=frozenset({GEO}), allowed_roots=(tmp_path,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        bounds.max_download_bytes = 1024  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        bounds.allowed_hosts = frozenset()  # type: ignore[misc]


def test_a_bounds_survives_the_way_to_a_worker(tmp_path: Path) -> None:
    """A trial passes the object to a spawn worker, so it must pickle."""
    bounds = Bounds(allowed_hosts=frozenset({GEO}), allowed_roots=(tmp_path,))
    restored = pickle.loads(pickle.dumps(bounds))
    assert restored == bounds
    assert restored.permits_host(GEO)
    assert restored.permits_path(tmp_path)
