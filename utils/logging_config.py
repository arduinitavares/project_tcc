from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from utils.failure_artifacts import LOGS_DIR


APP_LOG_PATH = LOGS_DIR / "app.log"
ERROR_LOG_PATH = LOGS_DIR / "error.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def _ensure_handler(logger: logging.Logger, handler: logging.Handler) -> None:
    for existing in logger.handlers:
        if type(existing) is type(handler):
            existing_path = getattr(existing, "baseFilename", None)
            new_path = getattr(handler, "baseFilename", None)
            if existing_path and new_path and Path(existing_path) == Path(new_path):
                return
    logger.addHandler(handler)


def _build_handler(path: Path, *, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    return handler


def configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    app_handler = _build_handler(APP_LOG_PATH, level=logging.INFO)
    error_handler = _build_handler(ERROR_LOG_PATH, level=logging.WARNING)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    _ensure_handler(root_logger, app_handler)
    _ensure_handler(root_logger, error_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.setLevel(logging.INFO)
        _ensure_handler(uvicorn_logger, app_handler)
        _ensure_handler(uvicorn_logger, error_handler)
