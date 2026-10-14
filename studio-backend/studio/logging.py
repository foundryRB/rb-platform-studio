"""Centralized logging configuration and logger factory."""

from __future__ import annotations

import logging
import sys

__all__ = ["configure_logging", "get_logger"]

_ROOT = "studio"
_FORMAT = "%(asctime)s  %(levelname)-5s  %(name)s  %(message)s"
_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once. Idempotent."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger(_ROOT)
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the project root namespace."""
    return logging.getLogger(f"{_ROOT}.{name}")
