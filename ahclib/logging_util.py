import logging
import os
import time
from copy import copy


class ElapsedFormatter(logging.Formatter):
    """Log formatter that shows elapsed time as ``MM:SS``."""

    def __init__(self) -> None:
        super().__init__("%(elapsed)s [%(levelname)s] : %(message)s")
        self._started_at = time.monotonic()

    def format(self, record: logging.LogRecord) -> str:
        elapsed_seconds = max(0, int(time.monotonic() - self._started_at))
        minutes, seconds = divmod(elapsed_seconds, 60)

        elapsed_record = copy(record)
        elapsed_record.elapsed = f"{minutes:02d}:{seconds:02d}"
        return super().format(elapsed_record)


def configure_elapsed_logging() -> None:
    """Configure the root logger to show time elapsed since this call."""

    handler = logging.StreamHandler()
    handler.setFormatter(ElapsedFormatter())
    logging.basicConfig(
        handlers=[handler],
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
