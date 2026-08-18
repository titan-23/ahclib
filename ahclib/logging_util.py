import logging
import os
import time
from copy import copy


class ElapsedFormatter(logging.Formatter):
    """起動後の経過時間を ``MM:SS`` 形式で表示する"""

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
    """この関数を呼んでからの経過時間をログに表示する"""

    handler = logging.StreamHandler()
    handler.setFormatter(ElapsedFormatter())
    logging.basicConfig(
        handlers=[handler],
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
