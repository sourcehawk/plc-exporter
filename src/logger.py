"""
This module contains a function to create a logger.
"""

import logging
from enum import Enum


class LogLevel(Enum):
    """
    The log levels that can be used.
    """

    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LowercaseLevelFormatter(logging.Formatter):
    """
    Converts the default log level to lowercase.
    """

    def format(self, record):
        record.levelname = record.levelname.lower()
        return super().format(record)


def create_logger(name: str, log_level: int = logging.DEBUG) -> logging.Logger:
    """
    Creates a console logger with the given name.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    ch = logging.StreamHandler()
    formatter = LowercaseLevelFormatter(
        'timestamp=%(asctime)s level=%(levelname)s message="%(message)s"',
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def set_level(logger: logging.Logger, log_level: int) -> None:
    """
    Set the log level of the logger.
    """
    logger.setLevel(log_level)
    for handler in logger.handlers:
        handler.setLevel(log_level)
