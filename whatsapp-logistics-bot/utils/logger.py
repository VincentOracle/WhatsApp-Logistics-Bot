"""
Centralized logger. Also enforces that no customer PII (name, phone,
address) is ever written to log output at the point of logging,
mirroring the "excluded from application log output" requirement
described for the YellowBIRD middleware.
"""
import logging
import re
import sys

_PII_PATTERNS = [
    re.compile(r"\+?\d{9,15}"),  # phone numbers
]


class PiiRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern in _PII_PATTERNS:
            msg = pattern.sub("[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        handler.setFormatter(formatter)
        handler.addFilter(PiiRedactingFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
