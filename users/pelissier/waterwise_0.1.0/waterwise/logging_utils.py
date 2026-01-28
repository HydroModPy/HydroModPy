# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 14:17:45 2026

@author: pelissierm
"""

import logging
from pathlib import Path


def setup_logger(name: str, log_file : Path = None, level: int = logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    
    fmt = logging.Formatter("%(levelname)s | %(name)s | %(message)s")
    
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setLevel(level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    
    return logger