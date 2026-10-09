"""Every ``HMP_*`` environment variable HydroModPy reads, in one table.

The code keeps reading its variables where it needs them. This module does not
read any of them: it declares each one once, with what happens when it is
unset, who it is for and what it does. The contributor documentation renders
this table, and ``tests/unit/architecture/test_env_vars_are_registered.py``
fails when a ``HMP_*`` name appears in the code without a row here, or when a
row names a variable nothing reads any more.

Scopes:

- ``user``: a person running HydroModPy may set it;
- ``dev``: for debugging or tracing the code, or set by HydroModPy itself;
- ``test``: read by the test suite or the validation cases;
- ``docs``: read by the documentation build.

A row is fixed here, next to the code it describes. A row is never typed in a
page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnvScope = Literal["user", "dev", "test", "docs"]

ENV_SCOPES: tuple[EnvScope, ...] = ("user", "dev", "test", "docs")
"""The scopes, in the order a reader meets them."""


@dataclass(frozen=True, slots=True)
class EnvVar:
    """One environment variable read by HydroModPy."""

    name: str
    """Full name, or the shared start of the names when :attr:`prefix` is set."""

    default: str
    """What the code does when the variable is unset, in words."""

    scope: EnvScope
    """Who the variable is for. See the module docstring."""

    description: str
    """What the variable does, with the values the code accepts."""

    prefix: bool = False
    """True when the code reads every variable whose name starts with :attr:`name`."""

    @property
    def display_name(self) -> str:
        """Name as a reader writes it: ``HMP_SET_<key>`` for a prefix."""
        return f"{self.name}<key>" if self.prefix else self.name


ENV_VARS: tuple[EnvVar, ...] = (
    # -- user -----------------------------------------------------------------
    EnvVar(
        "HMP_AUTH_BACKEND",
        "``local``",
        "user",
        "Name of the backend that says who acts, for the audit trail and the privacy "
        "purge. Only ``local`` ships. An unknown name raises ``ValueError``.",
    ),
    EnvVar(
        "HMP_AUTO_MIGRATE",
        "on",
        "user",
        "``0``, ``false``, ``no`` or ``off`` forbids the automatic schema upgrade of a "
        "DuckDB file when it is opened. A needed upgrade then raises "
        "``AutoMigrationDisabled``.",
    ),
    EnvVar(
        "HMP_AUTO_REGISTER_PROJECT",
        "on",
        "user",
        "``0``, ``false``, ``no`` or ``off`` stops the registration of project roots in "
        "the global index of the machine.",
    ),
    EnvVar(
        "HMP_BIN",
        "``bin/`` under the cache folder",
        "user",
        "Folder of the solver binaries. Replaces the managed folder under ``HMP_CACHE_HOME``.",
    ),
    EnvVar(
        "HMP_CACHE_HOME",
        "the user cache folder of the platform",
        "user",
        "Root of the machine cache: solver binaries and downloaded data.",
    ),
    EnvVar(
        "HMP_EXAMPLES_SOURCE",
        "the GitHub tag of the installed version",
        "user",
        "Replaces the whole prefix the example files are fetched from: a URL, a "
        "``file://`` URL or a local checkout. When it is set, ``--ref`` no longer "
        "applies.",
    ),
    EnvVar(
        "HMP_NO_PROGRESS",
        "unset",
        "user",
        "Any non-empty value turns off the live progress display on the console.",
    ),
    EnvVar(
        "HMP_PROGRESS_FILE",
        "unset, no file",
        "user",
        "Path of an NDJSON file. Each progress event is appended to it as one JSON "
        "line, for a supervisor that reads the file while the run goes on.",
    ),
    EnvVar(
        "HMP_PROJECT_ROOT",
        "``[workspace] project_root``, then the folder of the config file",
        "user",
        "Project root of a run. Wins over ``[workspace] project_root`` of the TOML.",
    ),
    EnvVar(
        "HMP_SET_",
        "unset",
        "user",
        "``hmp run`` reads each variable that starts with ``HMP_SET_`` as a TOML "
        "override. The rest of the name is the key, lowercased, with ``__`` for a dot: "
        "``HMP_SET_simulation__run_id``. The value is parsed as TOML. It wins over "
        "``--set``.",
        prefix=True,
    ),
    EnvVar(
        "HMP_SILENCE_MF6_VERSION_MISMATCH",
        "unset, the warning is shown",
        "user",
        "Any value other than empty, ``0``, ``false`` or ``no`` silences the warning "
        "shown when the MODFLOW 6 executable and libmf6 differ in major or minor version.",
    ),
    EnvVar(
        "HMP_STATE_HOME",
        "the user state folder of the platform",
        "user",
        "Root of the machine state, where the global index ``index.duckdb`` lives. The "
        "test suite points it at its scratch folder.",
    ),
    EnvVar(
        "HMP_USER",
        "``USER`` or ``USERNAME``, then the system user",
        "user",
        "Name of the person who acts, written in the audit trail.",
    ),
    EnvVar(
        "HMP_VERBOSITY",
        "``normal``",
        "user",
        "Console verbosity: ``quiet``, ``normal``, ``verbose`` or ``debug``. The command "
        "line reads ``--verbosity`` first, then this variable, then "
        "``[workflow] verbosity``.",
    ),
    EnvVar(
        "HMP_WORKSPACE",
        "the workspace found above the current folder, then ``~/hydromodpy``",
        "user",
        "Workspace root of the catalog, project and run commands when the command line gives none.",
    ),
    # -- dev ------------------------------------------------------------------
    EnvVar(
        "HMP_ALLOW_LEGACY_NPY_VALIDATION",
        "unset, refused",
        "dev",
        "``1`` lets the loaders of the validation cases read results saved as legacy "
        "``.npy`` files.",
    ),
    EnvVar(
        "HMP_DETERMINISTIC_FETCHED_AT",
        "unset, the fetch time is written",
        "dev",
        "``1`` writes no ``fetched_at`` in the provenance sidecar of a downloaded file, "
        "so the sidecar is the same bytes on every run.",
    ),
    EnvVar(
        "HMP_GMSH_VERBOSE",
        "unset, Gmsh is silent",
        "dev",
        "``1``, ``true``, ``yes`` or ``on`` keeps the terminal output of Gmsh.",
    ),
    EnvVar(
        "HMP_KEEP_TRIAL_SCRATCH",
        "unset, removed",
        "dev",
        "Any value other than empty, ``0``, ``false`` or ``no`` keeps the solver folder "
        "of each calibration trial and the preprocessing tree of the session.",
    ),
    EnvVar(
        "HMP_MESH_TRACE_FILE",
        "unset, no trace",
        "dev",
        "Path of a text file. Each stage of the Gmsh meshing appends one timestamped line to it.",
    ),
    EnvVar(
        "HMP_OUT_PATH",
        "``hydromodpy_validation_outputs`` in the system temporary folder",
        "dev",
        "Output root of the validation cases and of the investigation scripts under "
        "``tools/``. The validation results land under ``<HMP_OUT_PATH>/validation``.",
    ),
    EnvVar(
        "HMP_OVERVIEW_HTML_REVIEW_LEVELS",
        "unset",
        "dev",
        "``1``, ``true``, ``yes`` or ``on`` also writes the review pages of the data "
        "overview report (compact, standard, audit) and links them.",
    ),
    EnvVar(
        "HMP_PANDERA_STRICT",
        "unset, a warning is logged",
        "dev",
        "``1``, ``true``, ``yes`` or ``on`` makes a failed pandera schema check of an "
        "ingested table raise instead of logging a warning.",
    ),
    EnvVar(
        "HMP_RUN_SCRATCH",
        "unset outside a run",
        "dev",
        "Set by HydroModPy, never by hand: the scratch folder of the run this process "
        "is inside. A subprocess inherits it and works in the same folder.",
    ),
    EnvVar(
        "HMP_WHITEBOX_REDIRECT_NATIVE_STDIO",
        "redirect outside pytest, not under pytest",
        "dev",
        "Forces whether the native output of Whitebox is redirected at the file "
        "descriptor level. The test suite sets ``0``.",
    ),
    EnvVar(
        "HMP_WHITEBOX_VERBOSE",
        "unset, quiet",
        "dev",
        "A true value (``1``, ``true``, ``yes``, ``on``) turns on the verbose mode of Whitebox.",
    ),
    # -- test -----------------------------------------------------------------
    EnvVar(
        "HMP_COVERAGE",
        "unset",
        "test",
        "Any non-empty value runs the subprocesses of the regression tests and of the "
        "validation cases under a coverage wrapper.",
    ),
    EnvVar(
        "HMP_VALIDATION_RESULTS",
        "unset, nothing recorded",
        "test",
        "Directory where the validation tests write their measured values, thresholds, "
        "curves and outcomes, one ``part-*.json`` per pytest process. "
        "``tools/docs/validation_results.py`` merges them into the Validation page.",
    ),
    EnvVar(
        "HMP_REQUIRE_SYBIL",
        "unset, the guide blocks are skipped without sybil",
        "test",
        "Any non-empty value makes the test of the Python blocks of the guides fail when "
        "sybil is not installed, instead of skipping.",
    ),
    EnvVar(
        "HMP_RUN_HUBEAU_NETWORK_TESTS",
        "unset, skipped",
        "test",
        "``1`` runs the integration tests that call the Hub'Eau water-quality API.",
    ),
    EnvVar(
        "HMP_RUN_IGN_ASSEMBLY_TESTS",
        "unset, skipped",
        "test",
        "``1`` runs the integration test that downloads, extracts, merges and crops a "
        "real IGN DEM.",
    ),
    EnvVar(
        "HMP_RUN_IGN_DOWNLOAD_TESTS",
        "unset, skipped",
        "test",
        "``1`` runs the integration test that downloads one real IGN DEM archive.",
    ),
    EnvVar(
        "HMP_RUN_IGN_NETWORK_TESTS",
        "unset, skipped",
        "test",
        "``1`` runs the integration tests that call the IGN DEM service.",
    ),
    EnvVar(
        "HMP_TEST_SCRATCH_OWNER",
        "set by the first pytest process",
        "test",
        "Token of the pytest process that owns the scratch session. The workers and the "
        "subprocesses inherit it, so only the owner cleans the session.",
    ),
    EnvVar(
        "HMP_TEST_SCRATCH_ROOT",
        "``hydromodpy_tests`` in the system temporary folder",
        "test",
        "Scratch root of pytest and of the subprocesses it starts. Point it at a disk "
        "folder when the temporary folder is a small RAM disk.",
    ),
    EnvVar(
        "HMP_TEST_SESSION_SCRATCH_ROOT",
        "a new folder under the scratch root",
        "test",
        "Scratch folder of one test session. Set by the test conftest and by "
        "``hmp test``, inherited by the subprocesses.",
    ),
    EnvVar(
        "HMP_UPDATE_GOLDEN",
        "unset, compared",
        "test",
        "``1`` rewrites the golden signatures of the structured-grid field "
        "discretization test instead of comparing against them.",
    ),
    EnvVar(
        "HMP_WHEEL_SITE",
        "unset",
        "test",
        "Set in the environment of the installed-wheel proof. The forward-model "
        "contract test then requires a model found through its entry point.",
    ),
    # -- docs -----------------------------------------------------------------
    EnvVar(
        "HMP_DOC_VERSION",
        "``main``",
        "docs",
        "Version folder the site is built for: canonical URL and version switcher. The "
        "deploy workflow sets it.",
    ),
    EnvVar(
        "HMP_CHROMIUM",
        "unset, ``--chromium`` or the browser found on the PATH",
        "docs",
        "Chromium executable of the browser probe of the built site (``tools/docs/site_probe.py``).",
    ),
    EnvVar(
        "HMP_DOCS_COMMIT",
        "unset, ``GITHUB_SHA`` then ``git rev-parse HEAD``",
        "docs",
        "Commit the ``[source]`` links of the Python reference point to.",
    ),
    EnvVar(
        "HMP_DOCS_GOATCOUNTER_URL",
        "unset, no tracking",
        "docs",
        "GoatCounter ``count`` endpoint. When set, the pages count their views.",
    ),
    EnvVar(
        "HMP_DOCS_REPO",
        "``https://github.com/HydroModPy/HydroModPy``",
        "docs",
        "Repository the ``[source]`` links of the Python reference point to.",
    ),
    EnvVar(
        "HMP_DOCS_QUIET",
        "``1``",
        "docs",
        "Read by ``docs/Makefile``. ``1`` filters known noise from the build output, "
        "``0`` shows the raw stream.",
    ),
    EnvVar(
        "HMP_SKIP_CONTRACT_TABLES_GEN",
        "unset, regenerated",
        "docs",
        "``1`` skips the regeneration of the layer-matrix fragment at build time.",
    ),
    EnvVar(
        "HMP_SKIP_DOC_DATA",
        "unset, regenerated",
        "docs",
        "``1`` reuses the ``_data/*.json`` files of the previous build, when they exist.",
    ),
)
"""Every variable, grouped by scope and sorted by name inside a scope."""


def env_var(name: str) -> EnvVar:
    """Return the row of *name*, matching a prefix row too. Raises ``KeyError``."""
    for row in ENV_VARS:
        if row.name == name or (row.prefix and name.startswith(row.name)):
            return row
    raise KeyError(name)


__all__ = ["ENV_SCOPES", "ENV_VARS", "EnvScope", "EnvVar", "env_var"]
