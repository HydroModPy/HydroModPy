"""Console and file logging policy for HydroModPy.

One verbosity knob drives both what the console prints and whether the
live progress display runs:

======== ============================================ ================
level    console                                      live display
======== ============================================ ================
quiet    warnings and errors only                     off
normal   warnings, errors and milestones (default)    on
verbose  every INFO line                              on
debug    every DEBUG line, module and line number     off
======== ============================================ ================

A *milestone* is an INFO line the default level keeps: the phase
checkmarks, what a run wrote, how it ended. Emit one with
``logger.info(..., extra=MILESTONE)``, the marker
:mod:`hydromodpy.core.progress` defines. Everything else stays out of
the way at ``normal`` and is one ``--verbose`` away.

Only the console is filtered: the project debug log,
``.hmp/logs/hydromodpy_debug.log``, records DEBUG whatever the console
shows, so nothing is lost by running quiet.
"""

import logging
import os
import warnings

from hydromodpy.core import progress as core_progress
from hydromodpy.core.progress import MILESTONE_KEY

VERBOSITY_LEVELS: tuple[str, ...] = ("quiet", "normal", "verbose", "debug")
"""Accepted console verbosity levels, quietest first."""

DEFAULT_VERBOSITY = "normal"

_CONSOLE_LEVELS = {
    "quiet": logging.WARNING,
    "normal": logging.INFO,
    "verbose": logging.INFO,
    "debug": logging.DEBUG,
}


def normalize_verbosity(level: str) -> str:
    """Return the canonical name of *level*, raising on an unknown one."""
    name = str(level).strip().lower()
    if name not in VERBOSITY_LEVELS:
        raise ValueError(f"Invalid verbosity {level!r}. Use one of: {', '.join(VERBOSITY_LEVELS)}.")
    return name


class _MilestoneFilter(logging.Filter):
    """Keep WARNING and above, plus the INFO lines marked as milestones.

    This is what makes ``normal`` readable: a run emits hundreds of INFO
    lines that only matter while debugging it, and a handful that tell the
    user what happened. Only the marked ones survive here.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return bool(getattr(record, MILESTONE_KEY, False))


class _ConsoleFormatter(logging.Formatter):
    """Prefix a line with its level, except the ones at INFO and below.

    At ``normal`` the only INFO lines left are milestones, and a
    ``[INFO]`` in front of each adds a column of noise to the four lines
    that matter. A WARNING keeps its label, where it earns its place.
    """

    def __init__(self) -> None:
        super().__init__("[%(levelname)s] %(message)s")
        self._plain = logging.Formatter("%(message)s")

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno <= logging.INFO:
            return self._plain.format(record)
        return super().format(record)


class _DedupFilter(logging.Filter):
    """Drop a warning the console has already shown, verbatim.

    A catchment delineated twice snaps its outlet twice and warns twice
    about the same metres. The second line teaches nothing and pushes the
    first one up the scrollback. Console only: the file logs keep every
    occurrence, and DEBUG/INFO repetitions are left alone because they
    often carry a counter the user is reading.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[tuple[int, str]] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        key = (record.levelno, record.getMessage())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEPRECATION_CATEGORIES = (DeprecationWarning, PendingDeprecationWarning, FutureWarning)


def _is_third_party_deprecation(category, filename):
    """True for a deprecation a dependency raises about its own internals.

    ``rasterio`` multiplying two ``Affine`` objects, ``xarray`` setting the
    shape of a NumPy array: the user did not write that call and cannot fix
    it, so the line is demoted to DEBUG instead of warning about it on every
    run. Only deprecation-flavored categories qualify - a third-party
    RuntimeWarning about a dataset still reaches the console.

    Decided here, inside ``showwarning``, rather than with
    ``warnings.filterwarnings``: flopy's ``plot`` submodules install
    ``warnings.simplefilter("always", PendingDeprecationWarning)`` at import
    time, which always lands in front of a filter registered earlier and
    defeats it. ``showwarning`` is the one place every warning HydroModPy
    emits still passes through.
    """
    return issubclass(category, _DEPRECATION_CATEGORIES) and not os.path.abspath(
        filename
    ).startswith(_PACKAGE_ROOT)


class LogManager:
    """
    Manage logging for HydroModPy.

    Handles two types of logs:
    - Simulation log: automatic, in watershed folder, full debug level
    - User log: optional, in current directory, configurable level
    """

    _instance = None

    def __init__(
        self, mode=DEFAULT_VERBOSITY, log_dir=None, overwrite=False, verbose_libraries=False
    ):
        """
        Initialize the LogManager.

        Parameters
        ----------
        mode : str, optional
            Console verbosity, one of "quiet", "normal", "verbose" or "debug".
            Default is "normal". See the module docstring for what each level
            prints.
        log_dir : str, optional
            Directory for optional user log file.
            Default is None (no user log file created).
        overwrite : bool, optional
            Whether to overwrite existing log files. Default is False (append mode).
        verbose_libraries : bool, optional
            If True, library logs are set to WARNING; otherwise, they are set to CRITICAL.
            Default is False.
        """

        self.mode = normalize_verbosity(mode)
        self.log_dir = log_dir
        self.overwrite = overwrite
        self.verbose_libraries = verbose_libraries
        self.logger = logging.getLogger("hydromodpy")
        self.simulation_log_path = None

        # Store instance for global access
        LogManager._instance = self

        self._setup_logging()
        self._suppress_library_logs()
        self._route_warnings_to_logging()

    def _setup_logging(self):
        """
        Configure logging based on mode.
        Setup console handler, preserve file handlers.
        """

        # Remove console handlers, keep file handlers
        for handler in self.logger.handlers[:]:
            is_console = isinstance(
                handler, (logging.StreamHandler, core_progress.ConsoleLogHandler)
            )
            if is_console and not isinstance(handler, logging.FileHandler):
                self.logger.removeHandler(handler)

        # Keep the live progress display in sync with the console mode
        core_progress.set_console_mode(self.mode)

        # Set the base logger level
        self.logger.setLevel(logging.DEBUG)

        # Prevent propagation to avoid duplicate logs
        self.logger.propagate = False

        console_handler = core_progress.make_console_handler()
        console_handler.setLevel(_CONSOLE_LEVELS[self.mode])
        if self.mode == "debug":
            console_handler.setFormatter(
                logging.Formatter("[%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s")
            )
        elif self.mode == "normal":
            console_handler.setFormatter(_ConsoleFormatter())
            console_handler.addFilter(_DedupFilter())
            console_handler.addFilter(_MilestoneFilter())
        else:
            console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            console_handler.addFilter(_DedupFilter())
        self.logger.addHandler(console_handler)

        # Add user log if specified and not already added
        if self.log_dir is not None and not self._has_user_log_handler():
            self._add_user_log()

    def _add_user_log(self):
        """
        Add user log file handler.
        """
        log_file = os.path.join(self.log_dir, "hydromodpy.log")

        # Create directory if needed
        log_dir_path = os.path.dirname(log_file)
        if log_dir_path:
            os.makedirs(log_dir_path, exist_ok=True)

        file_mode = "w" if self.overwrite else "a"
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"
        )

        # User log respects the console mode level
        file_level = _CONSOLE_LEVELS[self.mode]

        user_handler = logging.FileHandler(log_file, mode=file_mode, encoding="utf-8")
        user_handler.setLevel(file_level)
        user_handler.setFormatter(file_formatter)
        user_handler.set_name("user_log")  # Mark this handler
        self.logger.addHandler(user_handler)

    def _has_user_log_handler(self):
        """
        Check if user log handler already exists.
        """
        for handler in self.logger.handlers:
            if hasattr(handler, "get_name") and handler.get_name() == "user_log":
                return True
        return False

    def set_simulation_log(self, watershed_folder):
        """
        Setup simulation log in watershed folder.
        Always captures DEBUG level, regardless of console mode.
        Called automatically by Watershed class.

        Parameters
        ----------
        watershed_folder : str
            Path to watershed folder
        """
        sim_log_dir = os.path.join(watershed_folder, ".hmp", "logs")
        self.simulation_log_path = os.path.join(sim_log_dir, "hydromodpy_debug.log")

        # Create the hidden log folder if needed
        os.makedirs(sim_log_dir, exist_ok=True)

        # Remove any existing simulation log handler
        for handler in self.logger.handlers[:]:
            is_simulation_handler = False
            if hasattr(handler, "get_name") and handler.get_name() == "simulation_log":
                is_simulation_handler = True
            if getattr(handler, "_hydromodpy_simulation_log", False):
                is_simulation_handler = True
            if isinstance(handler, logging.FileHandler) and handler.baseFilename == os.path.abspath(
                self.simulation_log_path
            ):
                is_simulation_handler = True
            if is_simulation_handler:
                self.logger.removeHandler(handler)
                handler.close()

        # Add simulation log handler (always DEBUG level)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"
        )
        candidate_paths = [
            self.simulation_log_path,
            os.path.join(sim_log_dir, f"hydromodpy_debug_{os.getpid()}.log"),
        ]
        for candidate_path in candidate_paths:
            try:
                sim_handler = logging.FileHandler(candidate_path, mode="a", encoding="utf-8")
            except PermissionError:
                continue
            self.simulation_log_path = candidate_path
            sim_handler.setLevel(logging.DEBUG)
            sim_handler.setFormatter(file_formatter)
            if hasattr(sim_handler, "set_name"):
                sim_handler.set_name("simulation_log")
            sim_handler._hydromodpy_simulation_log = True
            self.logger.addHandler(sim_handler)
            return

        self.simulation_log_path = None
        self.logger.warning(
            "Simulation log file is not writable in %s; continuing without file logging.",
            watershed_folder,
        )

    def set_console_level(self, mode):
        """
        Change console verbosity.

        Parameters
        ----------
        mode : str
            One of "quiet", "normal", "verbose" or "debug".
        """
        self.mode = normalize_verbosity(mode)
        self._setup_logging()

    def enable_user_log(self, log_dir=None):
        """
        Enable user log file.

        Parameters
        ----------
        log_dir : str, optional
            Directory for log file. If None, uses current working directory.
        """
        if log_dir is None:
            log_dir = os.getcwd()
        self.log_dir = log_dir
        self._add_user_log()

    def show_library_logs(self, show=True):
        """
        Show or hide logs from third-party libraries.

        Parameters
        ----------
        show : bool, optional
            If True, show library logs (WARNING level).
            If False, hide library logs (CRITICAL level only).
            Default is True.
        """
        self.verbose_libraries = show
        self._suppress_library_logs()

    @staticmethod
    def _route_warnings_to_logging():
        """Route ``warnings.warn`` output through the hydromodpy logger.

        Raw warnings written to stderr corrupt the live progress display;
        through logging they render above it and reach the file logs.
        """
        warnings_logger = logging.getLogger("hydromodpy.warnings")

        def showwarning(message, category, filename, lineno, file=None, line=None):
            del file, line
            emit = (
                warnings_logger.debug
                if _is_third_party_deprecation(category, filename)
                else warnings_logger.warning
            )
            emit("%s: %s (%s:%s)", category.__name__, message, filename, lineno)

        warnings.showwarning = showwarning

    def _suppress_library_logs(self):
        """
        Suppress logs from third-party libraries.
        """
        libraries_to_silence = [
            "fiona",
            "rasterio",
            "urllib3",
            "geopy",
            "matplotlib",
            "PIL",
            "shapely",
            "pyproj",
            "requests",
        ]

        level = logging.WARNING if self.verbose_libraries else logging.CRITICAL

        for library in libraries_to_silence:
            logging.getLogger(library).setLevel(level)


def get_logger(name):
    """
    Get a logger for use in HydroModPy modules.

    Parameters
    ----------
    name : str
        Name of the logger (typically __name__ in the module)

    Returns
    -------
    logging.Logger
        A logger instance

    Examples
    --------
    >>> from hydromodpy.core.logging import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Processing started")
    """
    if not name.startswith("hydromodpy"):
        name = f"hydromodpy.{name}"
    return logging.getLogger(name)


def set_verbosity(level):
    """Set the console verbosity of the running process.

    Parameters
    ----------
    level : str
        One of "quiet", "normal", "verbose" or "debug".

    Returns
    -------
    str
        The canonical level that was applied.
    """
    name = normalize_verbosity(level)
    if LogManager._instance is None:
        LogManager(mode=name)
    else:
        LogManager._instance.set_console_level(name)
    return name


def current_verbosity():
    """Return the console verbosity in force, without creating a manager."""
    if LogManager._instance is None:
        return DEFAULT_VERBOSITY
    return LogManager._instance.mode


def verbosity_from_env(env=None):
    """Return the verbosity named by ``HMP_VERBOSITY``, or None when unset."""
    source = os.environ if env is None else env
    raw = source.get("HMP_VERBOSITY")
    if not raw or not raw.strip():
        return None
    return normalize_verbosity(raw)


def setup_simulation_log(watershed_folder):
    """
    Setup simulation log in watershed folder.
    Helper function to be called by Watershed class.

    Parameters
    ----------
    watershed_folder : str
        Path to watershed output folder
    """
    if LogManager._instance is not None:
        LogManager._instance.set_simulation_log(watershed_folder)
