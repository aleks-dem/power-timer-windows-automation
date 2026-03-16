from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Iterable, List


DEFAULT_MAX_BYTES = 1_000_000   # 1MB
DEFAULT_BACKUPS = 8


@dataclass
class LogFiles:
    current: Path
    backups: list[Path]


def list_log_files(log_path: Path) -> LogFiles:
    # RotatingFileHandler: app.log, app.log.1, app.log.2 ...
    backups: list[Path] = []
    for p in log_path.parent.glob(log_path.name + ".*"):
        # include only numeric suffix
        suffix = p.name.replace(log_path.name + ".", "")
        if suffix.isdigit():
            backups.append(p)
    backups.sort(key=lambda x: int(x.name.split(".")[-1]), reverse=True)  # .8 (oldest) ... .1 (newest)
    return LogFiles(current=log_path, backups=backups)


def clear_logs(log_path: Path) -> None:
    lf = list_log_files(log_path)
    for p in lf.backups + [lf.current]:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def read_tail_lines(paths: Iterable[Path], max_lines: int = 2500) -> List[str]:
    # Read oldest -> newest for chronology:
    # backups are sorted .8..1, we reverse to read .8 first? Actually .8 oldest, yes:
    paths_list = list(paths)
    lines: list[str] = []
    for p in paths_list:
        try:
            content = p.read_text(encoding="utf-8", errors="replace").splitlines()
            lines.extend(content)
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
        except Exception:
            continue
    return lines


class UiQueueLogHandler(logging.Handler):
    """
    Push formatted log lines into a queue via callback to avoid importing UI types here.
    """
    def __init__(self, push_line_cb, level=logging.INFO):
        super().__init__(level)
        self._push = push_line_cb

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._push(msg)
        except Exception:
            pass


def setup_logging(
    log_path: Path,
    push_ui_line_cb=None,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS
) -> logging.Logger:
    logger = logging.getLogger("powertimer")
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers if re-initialized
    if getattr(logger, "_configured", False):
        return logger

    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    if push_ui_line_cb is not None:
        ui_handler = UiQueueLogHandler(push_ui_line_cb, level=level)
        ui_handler.setFormatter(fmt)
        logger.addHandler(ui_handler)

    logger._configured = True
    logger.info("Logger initialized: %s", log_path)
    return logger
