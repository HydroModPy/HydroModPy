"""What :class:`Bounds` permits, and what it refuses by name.

The refusals carry the sentence a reader acts on: the host or the path that
stepped out, the list the call honours, and the option that widens it. The
object is pickled to worker processes and frozen, so a trial cannot widen
its own call halfway through.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import BoundsError
from hydromodpy.core.runtime.bounds import Bounds

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


# --------------------------------------------------------------------------- #
# permits_path
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# The object itself
# --------------------------------------------------------------------------- #
