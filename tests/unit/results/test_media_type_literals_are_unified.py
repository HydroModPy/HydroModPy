"""Media type strings live in one table, and the table's values are pinned.

An artefact carries its media type in three places (capability declaration,
``outcome.json`` output record, ``manifest.json`` artefact record). Each
place that spells the string as a literal instead of importing
``hydromodpy.schema.media_types`` is a chance to drift by one character
(a missing space in ``image/tiff; application=geotiff`` is enough for an
orchestrator filtering on the type to miss the file it asked for).

Two independent gates:

- ``test_media_types_table_values_are_pinned`` imports the module and checks
  its constants by value, so a drifted string, a silently removed constant
  or a silently added one all fail. This is the one that actually reads the
  table's content; the literal scan below only checks that nothing outside
  the table repeats a string.
- ``test_no_stray_media_type_literals_outside_the_table`` scans source text
  for a quoted media type literal and fails on any hit that is not either
  the table itself or an explicitly named, justified exception.

The scan covers the whole package, and that is the measurement, not a
preference: the six call sites of ``GEOTIFF_MEDIA_TYPE``, the three of
``GEOPACKAGE_MEDIA_TYPE`` and the only one of ``NETCDF_MEDIA_TYPE`` all live
under ``spatial/`` and ``data/fetch/``, none under ``results/`` or
``schema/``. A gate scoped to the exporters would leave every writer of the
drift it exists to catch outside its reach - including four runtime paths
that stamp ``media_type`` into ``outcome.json`` and ``manifest.json``.

Scanning wide costs one thing: the four legitimate foreign literals it meets
belong to other slices of the codebase, one of them in a package another
session owns. So an allowlist entry pins a path and the media type string,
never the whole line: reformatting that line, renaming around it or moving it
leaves this gate green, while adding a new literal in the same file does not.
"""

from __future__ import annotations

import re
from pathlib import Path

import hydromodpy.schema.media_types as media_types_module

# Anchored on this file's own location (decision D211): a test that scans
# from ``Path.cwd()`` silently reads nothing when pytest is invoked from a
# different directory, and a silent empty scan is a green test that proves
# nothing.
HMP_ROOT = Path(__file__).resolve().parents[3] / "hydromodpy"

# The table itself: every constant here is expected to hold a literal.
MEDIA_TYPES_MODULE = HMP_ROOT / "schema" / "media_types.py"

# The whole package. An artefact media type is stamped by the exporters under
# results/, by the job and process models under schema/, and by the capability
# and worker modules under spatial/ and data/fetch/ - and it is those last two
# that hold every call site of the geotiff, geopackage and netcdf constants.
SCAN_ROOTS: tuple[Path, ...] = (HMP_ROOT,)

# Both quote styles. ``ruff format`` normalises this file tree to double
# quotes, so a single-quoted literal should not survive the format gate, but a
# scan that depends on another gate running first is a scan with a hole in it.
LITERAL_PATTERN = re.compile(r"""(["'])(?:application|image|text|video|audio)/[^"']*\1""")

# The four literals in the package that are not artefact media types, and so
# not the table's business. Each entry is (path suffix, the media type string
# itself) -- never the surrounding line, so the entry survives a reformat of
# code this slice does not own. A new literal in the same file still fails.
#
# The first two live under hydromodpy/cli/, a package another session owns.
# Pinning the string rather than the line is what keeps that ownership from
# reaching this gate.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    # Content-Type a local dev server writes on its own HTTP responses.
    ("cli/commands/dev/manage/server.py", "text/html; charset=utf-8"),
    ("cli/commands/dev/manage/server.py", "application/json; charset=utf-8"),
    # A query parameter the BD TOPAGE API defines, sent to it verbatim.
    (
        "data/variables/hydrography/apis/bdtopage.py",
        "application/json; subtype=geojson",
    ),
    # The Accept header the GitHub API requires.
    ("physics/hydrology/pyhelp/core/paths.py", "application/vnd.github+json"),
)

# Pinned by hand from hydromodpy/schema/media_types.py (read character by
# character, not from memory). A value drifting by one character, a
# constant silently removed, or a constant added without being pinned here
# all fail this comparison -- dict equality catches all three at once.
EXPECTED_MEDIA_TYPES: dict[str, str] = {
    "JSON_MEDIA_TYPE": "application/json",
    "GEOJSON_MEDIA_TYPE": "application/geo+json",
    "GEOPACKAGE_MEDIA_TYPE": "application/geopackage+sqlite3",
    "GEOTIFF_MEDIA_TYPE": "image/tiff; application=geotiff",
    "NETCDF_MEDIA_TYPE": "application/netcdf",
    "OCTET_STREAM_MEDIA_TYPE": "application/octet-stream",
    "PARQUET_MEDIA_TYPE": "application/vnd.apache.parquet",
    "TOML_MEDIA_TYPE": "application/toml",
    "ZARR_MEDIA_TYPE": "application/x.zarr-store",
}

# Below this, the scanned tree is gutted rather than merely reorganised.
# Set near the real count (1584 modules as of this writing), not at a
# fraction of it: the largest single sub-package holds 328, so a floor set
# low enough to tolerate an anchor that collapsed onto one of them would
# tolerate losing everything else too.
MINIMUM_SCANNED_FILES = 1400


def _is_allowlisted(path: Path, literal: str) -> bool:
    """True when this exact media type, in this file, is a named exception."""
    posix = path.as_posix()
    return any(posix.endswith(suffix) and literal == media_type for suffix, media_type in ALLOWLIST)


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _scan_for_stray_literals(files: list[Path]) -> list[tuple[Path, int, str]]:
    offending: list[tuple[Path, int, str]] = []
    for path in files:
        if path == MEDIA_TYPES_MODULE:
            continue
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            found = LITERAL_PATTERN.search(raw_line)
            if found is None:
                continue
            if _is_allowlisted(path, found.group(0)[1:-1]):
                continue
            offending.append((path, lineno, raw_line.strip()))
    return offending


def test_scan_reads_the_real_tree() -> None:
    """Guard the gate itself: an anchor bug must not read zero files silently."""
    files = _iter_python_files()
    assert len(files) >= MINIMUM_SCANNED_FILES, (
        f"expected at least {MINIMUM_SCANNED_FILES} Python files under {SCAN_ROOTS}, "
        f"found {len(files)}; the scan is probably anchored on the wrong directory"
    )


def test_media_types_module_is_a_file() -> None:
    """Independent of the scan: this specific path must exist on disk.

    Does not share the ``_iter_python_files`` anchoring with the floor
    above, so a mutation that breaks the floor's counting does not also
    silently pass this one.
    """
    assert MEDIA_TYPES_MODULE.is_file()


def test_scan_includes_a_known_results_export_file() -> None:
    """Independent of the floor: one specific, known file must be scanned.

    The floor counts; it does not say what was counted. This names a file,
    so a ``SCAN_ROOTS`` narrowed to a subtree that still clears the floor,
    or a floor lowered later, cannot quietly drop the exporters.
    """
    context_module = HMP_ROOT / "results" / "export" / "context.py"
    assert context_module in _iter_python_files()


def test_media_types_table_values_are_pinned() -> None:
    """The table's constants, by value -- not just their count or their names.

    Building ``actual`` from the imported module (not from re-reading the
    source text) means this test exercises the real, imported values: a
    constant reassigned after definition, or shadowed, would show up here.
    """
    actual = {
        name: value
        for name, value in vars(media_types_module).items()
        if name.endswith("_MEDIA_TYPE") and isinstance(value, str)
    }
    assert actual == EXPECTED_MEDIA_TYPES


def test_no_stray_media_type_literals_outside_the_table() -> None:
    files = _iter_python_files()
    offending = _scan_for_stray_literals(files)
    if offending:
        report = "\n".join(f"{path}:{lineno}: {line}" for path, lineno, line in offending)
        raise AssertionError(
            "Media type literals found outside hydromodpy/schema/media_types.py:\n"
            + report
            + "\n\nImport the matching *_MEDIA_TYPE constant, or add a justified "
            "entry to ALLOWLIST in this test."
        )
