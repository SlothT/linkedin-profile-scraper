from __future__ import annotations

import logging
import re
from collections.abc import Iterable

_LI_AT_SHAPE = re.compile(r"AQ[A-Za-z0-9_\-]{20,}")


def _redact_text(value: object, secrets: tuple[str, ...]) -> object:
    if not isinstance(value, str):
        return value
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return _LI_AT_SHAPE.sub("[REDACTED]", redacted)


class _RedactFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_text(record.msg, self._secrets)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: _redact_text(item, self._secrets) for key, item in record.args.items()}
            else:
                record.args = tuple(_redact_text(item, self._secrets) for item in record.args)
        return True


def configure_logging(secrets: Iterable[str]) -> None:
    """Install a logging filter that replaces any occurrence of each secret with '[REDACTED]'."""
    secret_tuple = tuple(secret for secret in secrets if secret)
    redact_filter = _RedactFilter(secret_tuple)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root_logger.handlers:
        handler.addFilter(redact_filter)
    root_logger.addFilter(redact_filter)
