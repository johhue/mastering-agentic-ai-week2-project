"""Shared helpers for the project command-line scripts."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, TypeVar

from dotenv import load_dotenv


T = TypeVar("T")
DEFAULT_LOG_FORMAT = "%(message)s"
DEBUG_LOG_FORMAT = "%(levelname)s: %(message)s"
FILE_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_LEVEL_ENV = "LOG_LEVEL"
LOG_FILE_ENV = "LOGGER_FILE"


def configure_logging(debug: bool = False, level: int = logging.INFO) -> None:
    """Configure console and optional file logging for CLI scripts.

    The function loads `.env` before reading logging settings. Set
    `LOGGER_FILE` in `.env` to write logs to a file, and set `LOG_LEVEL` to
    choose the non-debug logging level. Called by CLI main functions such as
    query_pinecone.main, query_openai.main, query_openai_pinecone.main,
    generate_test_questions.main, and upsert_to_pinecone.main.

    Args:
        debug: When true, enable debug output and include the log level prefix.
        level: Fallback non-debug logging level when LOG_LEVEL is not set.
    """
    load_environment()
    log_level = logging.DEBUG if debug else get_log_level(default=level)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(DEBUG_LOG_FORMAT if debug else DEFAULT_LOG_FORMAT)
    )
    handlers: list[logging.Handler] = [console_handler]

    log_file = os.getenv(LOG_FILE_ENV)
    if log_file:
        ensure_parent_directory(log_file)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT))
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True,
    )


def get_log_level(default: int = logging.INFO) -> int:
    """Return the configured logging level from the LOG_LEVEL environment value.

    Called by configure_logging when debug logging is not explicitly requested.

    Args:
        default: Level returned when LOG_LEVEL is unset or invalid.
    """
    configured_level = os.getenv(LOG_LEVEL_ENV)
    if not configured_level:
        return default

    level = logging.getLevelName(configured_level.upper())
    if isinstance(level, int):
        return level
    return default


def ensure_parent_directory(file_path: str) -> None:
    """Create the parent directory for a log file path when one is provided.

    Called by configure_logging before creating a file handler for LOGGER_FILE.

    Args:
        file_path: Log file path from LOGGER_FILE.
    """
    parent = Path(file_path).expanduser().parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def load_environment(override: bool = True) -> None:
    """Load variables from the local .env file into the process environment.

    Called by configure_logging and parse_args functions across the CLI scripts,
    and by support_chatbot at import time before Streamlit reads configuration.

    Args:
        override: Whether values from .env should replace existing environment
            variables.
    """
    load_dotenv(override=override)


def get_required_env(
    name: str,
    error_cls: type[Exception] = RuntimeError,
    message: str | None = None,
) -> str:
    """Return a required environment variable or raise a caller-selected error.

    Called by CLI main functions that need credentials, including
    query_pinecone.main, query_openai.main, query_openai_pinecone.main, and
    generate_test_questions.main.

    Args:
        name: Environment variable name to read.
        error_cls: Exception class to instantiate if the variable is missing.
        message: Optional custom error message for missing values.
    """
    value = os.getenv(name)
    if not value:
        raise error_cls(message or f"Missing {name}. Add it to .env.")
    return value


def get_field(value: Any, field_name: str, default: Any = None) -> Any:
    """Read a field from either a mapping or an object attribute.

    Called by response-normalization code in query_pinecone and
    query_openai_pinecone when SDK responses may be dict-like or object-like.

    Args:
        value: Mapping or object to read.
        field_name: Field or attribute name to retrieve.
        default: Value returned when the field is absent.
    """
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def get_int_field(value: Any, field_name: str) -> int:
    """Read a field and coerce missing or null values to zero.

    Called by query_openai_pinecone usage parsing helpers for embedding and
    chat completion responses.

    Args:
        value: Mapping or object to read.
        field_name: Field or attribute name to retrieve.
    """
    raw_value = get_field(value, field_name, 0)
    if raw_value is None:
        return 0
    return int(raw_value)


def batched(items: Sequence[T], batch_size: int) -> Iterator[Sequence[T]]:
    """Yield fixed-size slices from a sequence.

    Called by query_pinecone.summarize_sources and upsert_to_pinecone.upsert_chunks
    to keep fetch, embedding, and upsert request sizes bounded.

    Args:
        items: Sequence to split into batches.
        batch_size: Maximum number of items per yielded batch.
    """
    if batch_size <= 0:
        raise ValueError("batch size must be greater than zero")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]
