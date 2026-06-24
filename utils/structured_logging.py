from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging import LogRecord
from pathlib import Path
from typing import Any

from app.settings import load_settings


class JsonFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key.removeprefix("ctx_")] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    settings = load_settings()
    log_path: Path = settings.app_log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    if any(isinstance(handler.formatter, JsonFormatter) for handler in root_logger.handlers):
        return

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
