import logging
import os
import sys
import re
from typing import Optional

_CONFIGURED = False

class _TagFilter(logging.Filter):
    def __init__(self, tag_env: str = "PROCESS_TAG"):
        super().__init__()
        self._env = tag_env
    def filter(self, record: logging.LogRecord) -> bool:
        record.tag = os.getenv(self._env, "")
        return True

def _level_from_env() -> int:
    lv = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, lv, logging.INFO)

class _RedactTelegramBotTokenFilter(logging.Filter):
    """
    Redact Telegram bot token from any log message:
      https://api.telegram.org/bot<TOKEN>/...
    """
    _re = re.compile(r"(https://api\.telegram\.org/bot)(\d+:[A-Za-z0-9_-]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            redacted = self._re.sub(r"\1<REDACTED>", msg)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:
            pass
        return True


def configure_logging() -> None:
    """
    Единая настройка рут-логгера, чтобы не было дублей от разных модулей.
    Вызывается лениво через get_logger().
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(_level_from_env())

    # убрать уже навешанные хендлеры (во избежание дублей)
    for h in list(root.handlers):
        root.removeHandler(h)

    # формат: добавляем тег процесса, если задан PROCESS_TAG
    class _Fmt(logging.Formatter):
        def format(self, record):
            if getattr(record, "tag", ""):
                record.tag = f" [{record.tag}]"
            else:
                record.tag = ""
            return super().format(record)

    fmt = "%(asctime)s [%(levelname)s] [%(name)s]%(tag)s: %(message)s"
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_Fmt(fmt))
    handler.addFilter(_TagFilter())
    root.addHandler(handler)

    # 1) Do not let httpx/httpcore print full request URLs (they include Telegram bot token).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # 2) Hard redaction guard (even if someone enables INFO/DEBUG for httpx later).
    root.addFilter(_RedactTelegramBotTokenFilter())

    # перехват предупреждений и запрет “самодельных” хендлеров в дочерних логгерах
    logging.captureWarnings(True)
    _CONFIGURED = True

def get_logger(name: Optional[str] = None) -> logging.Logger:
    configure_logging()
    lg = logging.getLogger(name if name else __name__)
    # никаких локальных хендлеров — только propagate к root
    lg.propagate = True
    return lg
