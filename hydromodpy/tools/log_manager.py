import logging
import os

class LogManager:
    """
    Manage logging for HydroModPy.

    Handles two types of logs:
    - Simulation log: automatic, in watershed folder, full debug level
    - User log: optional, in current directory, configurable level
    """

    _instance = None

    def __init__(self, mode="verbose", log_dir=None, overwrite=False, verbose_libraries=False):
        """
        Initialize the LogManager.

        Parameters
        ----------
        mode : str, optional
            Console logging mode, "dev", "verbose", or "quiet". Default is "verbose".
            - "dev": Shows all messages (DEBUG and above) in console
            - "verbose": Shows INFO and above in console
            - "quiet": Shows WARNING and above in console
        log_dir : str, optional
            Directory for optional user log file.
            Default is None (no user log file created).
        overwrite : bool, optional
            Whether to overwrite existing log files. Default is False (append mode).
        verbose_libraries : bool, optional
            If True, library logs are set to WARNING; otherwise, they are set to CRITICAL.
            Default is False.
        """

        self.mode = mode
        self.log_dir = log_dir
        self.overwrite = overwrite
        self.verbose_libraries = verbose_libraries
        self.logger = logging.getLogger("hydromodpy")
        self.simulation_log_path = None

        # Store instance for global access
        LogManager._instance = self

        # Validate mode
        if self.mode not in ["dev", "verbose", "quiet"]:
            raise ValueError("Invalid mode. Use 'dev', 'verbose' or 'quiet'.")

        self._setup_logging()
        self._suppress_library_logs()

    def _setup_logging(self):
        """
        Configure logging based on mode.
        Setup console handler, preserve file handlers.
        """

        # Remove console handlers, keep file handlers
        for handler in self.logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                self.logger.removeHandler(handler)

        # Set the base logger level
        self.logger.setLevel(logging.DEBUG)

        # Prevent propagation to avoid duplicate logs
        self.logger.propagate = False

        # Create formatters
        detailed_formatter_console = logging.Formatter(
            "[%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"
        )
        simple_formatter_console = logging.Formatter("[%(levelname)s] %(message)s")

        # Console handler based on mode
        if self.mode == "dev":
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(detailed_formatter_console)
            self.logger.addHandler(console_handler)

        elif self.mode == "verbose":
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(simple_formatter_console)
            self.logger.addHandler(console_handler)

        elif self.mode == "quiet":
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            console_handler.setFormatter(simple_formatter_console)
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

        file_mode = 'w' if self.overwrite else 'a'
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"
        )

        # User log respects the console mode level
        level_map = {"dev": logging.DEBUG, "verbose": logging.INFO, "quiet": logging.WARNING}
        file_level = level_map.get(self.mode, logging.INFO)

        user_handler = logging.FileHandler(log_file, mode=file_mode, encoding='utf-8')
        user_handler.setLevel(file_level)
        user_handler.setFormatter(file_formatter)
        user_handler.set_name("user_log")  # Mark this handler
        self.logger.addHandler(user_handler)

    def _has_user_log_handler(self):
        """
        Check if user log handler already exists.
        """
        for handler in self.logger.handlers:
            if hasattr(handler, 'get_name') and handler.get_name() == "user_log":
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
        self.simulation_log_path = os.path.join(watershed_folder, "hydromodpy_debug.log")

        # Create folder if needed
        os.makedirs(watershed_folder, exist_ok=True)

        # Remove any existing simulation log handler
        for handler in self.logger.handlers[:]:
            if isinstance(handler, logging.FileHandler) and handler.baseFilename == os.path.abspath(self.simulation_log_path):
                self.logger.removeHandler(handler)
                handler.close()

        # Add simulation log handler (always DEBUG level)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s"
        )
        sim_handler = logging.FileHandler(self.simulation_log_path, mode='a', encoding='utf-8')
        sim_handler.setLevel(logging.DEBUG)
        sim_handler.setFormatter(file_formatter)
        self.logger.addHandler(sim_handler)

    def set_console_level(self, mode):
        """
        Change console logging level.

        Parameters
        ----------
        mode : str
            Logging mode: "dev", "verbose", or "quiet"
        """
        if mode not in ["dev", "verbose", "quiet"]:
            raise ValueError("Invalid mode. Use 'dev', 'verbose' or 'quiet'.")
        self.mode = mode
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
    >>> from hydromodpy.tools import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Processing started")
    """
    if not name.startswith("hydromodpy"):
        name = f"hydromodpy.{name}"
    return logging.getLogger(name)


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
