# -*- coding: utf-8 -*-
"""
 * Copyright (c) 2023 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

import logging
import os

class LogManager:
    """
    A class to configure and manage logging for the application.
    """

    def __init__(self, mode="verbose", log_dir="logs", overwrite=True, verbose_libraries=False):
        """
        Initialize the LogManager.

        Parameters
        ----------
        mode : str, optional
            Logging mode, "dev" or "user". Default is "user".
            - "dev": Logs all messages (DEBUG and above) to both console and file.
            - "verbose": Logs INFO and above messages to both console and file.
            - "quiet": Logs WARNING and above messages to both console and file.
        log_dir : str, optional
            Directory where log files will be saved. Default is "logs".
        overwrite : bool, optional
            Whether to overwrite existing log files. Default is True.
        verbose_libraries : bool, optional
            If True, library logs are set to WARNING; otherwise, they are set to CRITICAL.
        """
        
        self.mode = mode
        self.log_dir = log_dir
        self.overwrite = overwrite
        self.verbose_libraries = verbose_libraries
        self.logger = logging.getLogger()

        # Validate mode
        if self.mode not in ["dev", "verbose", "quiet"]:
            raise ValueError("Invalid mode. Use 'dev', 'verbose' or 'quiet'.")

        self._setup_logging()
        self._suppress_library_logs()

    def _setup_logging(self):
        """
        Configure the logging settings based on the mode.
        """
        # Ensure the log directory exists
        os.makedirs(self.log_dir, exist_ok=True)

        # Remove existing handlers to prevent duplicates
        # This is necessary when the LogManager is re-initialized (e.g., in a Jupyter notebook or Spyder)
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # Define log file paths
        log_file = os.path.join(self.log_dir, "dev.log")

        # Set the base logger level
        self.logger.setLevel(logging.DEBUG)

        # Create formatters
        detailed_formatter_file = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s")
        detailed_formatter_console = logging.Formatter("[%(levelname)s] [%(name)s] [%(module)s:%(lineno)d] %(message)s")
        simple_formatter_console = logging.Formatter("[%(levelname)s] %(message)s")

        # Determine file mode based on overwrite parameter
        file_mode = 'w' if self.overwrite else 'a'

        if self.mode == "dev":
            # Console handler for dev mode
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(detailed_formatter_console)
            self.logger.addHandler(console_handler)
            
        elif self.mode == "verbose":
            # Console handler for verbose mode
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(simple_formatter_console)
            self.logger.addHandler(console_handler)
            
        elif self.mode == "quiet":
            # Console handler for quiet mode
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            console_handler.setFormatter(simple_formatter_console)
            self.logger.addHandler(console_handler)

        # File handler for logs (DEBUG and above)
        # This handler is used in all modes (allows verbose and quiet mode to easily share debug logs)
        dev_file_handler = logging.FileHandler(log_file, mode=file_mode, encoding='utf-8')
        dev_file_handler.setLevel(logging.DEBUG)
        dev_file_handler.setFormatter(detailed_formatter_file)
        self.logger.addHandler(dev_file_handler)

    def _suppress_library_logs(self):
        """
        Suppress logs from third-party libraries while keeping custom logs visible.
        """
        libraries_to_silence = [
            "fiona",
            "rasterio",
            "urllib3",
            "geopy",
        ]

        level = logging.WARNING if self.verbose_libraries else logging.CRITICAL

        for library in libraries_to_silence:
            logging.getLogger(library).setLevel(level)