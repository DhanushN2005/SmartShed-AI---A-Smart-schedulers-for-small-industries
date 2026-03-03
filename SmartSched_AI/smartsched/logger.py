"""
SmartSched AI – Structured Logger
===================================
Wraps loguru for severity-level logging to stdout + rotating file.
Import `logger` from this module everywhere in the project.
"""

import sys
from pathlib import Path

try:
    from loguru import logger as _loguru_logger
    _loguru_available = True
except ImportError:
    _loguru_available = False

try:
    from config import LOG_LEVEL, LOG_FILE, LOG_ROTATION, LOG_RETENTION
except ImportError:
    LOG_LEVEL     = "INFO"
    LOG_FILE      = "logs/smartsched.log"
    LOG_ROTATION  = "10 MB"
    LOG_RETENTION = "30 days"


def _setup_loguru():
    """Configure loguru with console + rotating file handler."""
    _loguru_logger.remove()  # remove default handler

    # Console – coloured
    _loguru_logger.add(
        sys.stdout,
        level=LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> – <level>{message}</level>"
        ),
        colorize=True,
    )

    # File – rotating
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _loguru_logger.add(
        str(log_path),
        level=LOG_LEVEL,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} – {message}",
        encoding="utf-8",
    )

    return _loguru_logger


class _FallbackLogger:
    """Stdlib-based fallback when loguru is not installed."""
    import logging as _logging

    def __init__(self):
        import logging
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d – %(message)s",
        )
        self._log = logging.getLogger("smartsched")

    def info(self, msg, *a, **kw):    self._log.info(str(msg))
    def debug(self, msg, *a, **kw):   self._log.debug(str(msg))
    def warning(self, msg, *a, **kw): self._log.warning(str(msg))
    def error(self, msg, *a, **kw):   self._log.error(str(msg))
    def critical(self, msg, *a, **kw):self._log.critical(str(msg))
    def success(self, msg, *a, **kw): self._log.info(f"✔ {msg}")
    def bind(self, **kw):             return self


if _loguru_available:
    logger = _setup_loguru()
else:
    logger = _FallbackLogger()
