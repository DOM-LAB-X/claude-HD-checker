"""File logging for the packaged app.

When built with --windowed, there is no console: sys.stdout/sys.stderr are
None, so any print() raises AttributeError, and uncaught exceptions vanish.
setup_logging() creates data/logs/app.log and, when stdout/stderr are None,
redirects them to the logger so existing print() calls keep working and
nothing is lost.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from src.config import PROJECT_ROOT

_logger = None


class _LogWriter:
    """File-like object that forwards writes to a logger."""

    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        message = message.strip()
        if message:
            self.logger.log(self.level, message)

    def flush(self):
        pass


def setup_logging():
    global _logger
    if _logger is not None:
        return _logger

    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("hd_tracker")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)

    # --windowed builds have no console; print()/uncaught tracebacks would
    # otherwise raise or vanish.
    if sys.stdout is None:
        sys.stdout = _LogWriter(logger, logging.INFO)
    if sys.stderr is None:
        sys.stderr = _LogWriter(logger, logging.ERROR)

    _logger = logger
    return logger


def get_logger():
    return _logger or setup_logging()
