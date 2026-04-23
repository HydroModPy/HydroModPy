"""Human-readable filesystem naming for simulation storage.

A simulation's on-disk artefacts (Zarr store, Parquet directory) are placed
under ``simulations/<basename>.zarr`` / ``.parquet``, where ``<basename>`` is
built from the simulation's ``(project, name, sim_id)`` so a plain ``ls`` of
the workspace is readable. Older workspaces that pre-date this scheme use
the bare ``sim_id`` as the basename - callers that resolve paths must query
``simulations.storage_basename`` from the catalog and fall back to ``sim_id``
when it is ``NULL``.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

_SAFE_CHAR_RE = re.compile(r"[^a-z0-9_-]+")
_COLLAPSE_UNDERSCORE_RE = re.compile(r"_+")

MAX_SEGMENT_LEN = 32
SHORT_ID_LEN = 8
SEPARATOR = "__"
UNNAMED = "unnamed"


def sanitize_segment(value: str | None, *, max_len: int = MAX_SEGMENT_LEN) -> str:
    """Return a filesystem-safe lowercase slug from an arbitrary string.

    Accented characters are folded to ASCII (``"écoulement"`` → ``"ecoulement"``)
    and every remaining non-alphanumeric/underscore/hyphen character is
    replaced by an underscore. Runs of underscores collapse to one and the
    result is trimmed on both ends. An empty or whitespace-only input maps
    to ``"unnamed"``.
    """
    if not value:
        return UNNAMED
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    slug = _SAFE_CHAR_RE.sub("_", folded.strip().lower())
    slug = _COLLAPSE_UNDERSCORE_RE.sub("_", slug).strip("_-")
    if not slug:
        return UNNAMED
    return slug[:max_len].rstrip("_-") or UNNAMED


def short_uuid(sim_id: str | UUID) -> str:
    """Return the first :data:`SHORT_ID_LEN` hex characters of ``sim_id``."""
    return str(sim_id).replace("-", "")[:SHORT_ID_LEN]


def build_storage_basename(
    project: str | None,
    name: str | None,
    sim_id: str | UUID,
) -> str:
    """Build the on-disk basename for a simulation's Zarr / Parquet folder.

    The format is ``{project}__{name}__{shortuuid}``; missing ``project`` or
    ``name`` fall back to ``"unnamed"`` so the short UUID still guarantees
    uniqueness within the workspace.
    """
    return SEPARATOR.join(
        (
            sanitize_segment(project),
            sanitize_segment(name),
            short_uuid(sim_id),
        )
    )
