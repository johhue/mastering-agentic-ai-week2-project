"""Repository-root .env configuration and safe activity logging."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


class ResearchError(RuntimeError):
    """A research operation failed with a safe, actionable public message."""


def load_environment() -> None:
    """Load root .env from any working directory without overwriting test overrides."""
    load_dotenv(ROOT / '.env', override=False)


def required(name: str) -> str:
    """Read a required setting, identifying missing keys without exposing values."""
    value = os.getenv(name, '').strip()
    if not value:
        raise ResearchError(f'Configure {name} in the repository .env file.')
    return value


def integer(name: str, default: int, minimum: int = 1, maximum: int = 1000000) -> int:
    """Validate bounded integer settings without echoing invalid values."""
    try:
        value = int(os.getenv(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError('outside bounds')
        return value
    except ValueError as config_error:
        raise ResearchError(f'{name} must be an integer from {minimum} to {maximum}.') from config_error


def configure_logging() -> None:
    """Log agent stages and counts, suppressing SDK payloads and database secrets."""
    load_environment()
    level_name = 'DEBUG' if os.getenv('P3_DEBUG', 'false').lower() == 'true' else os.getenv('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers = [logging.StreamHandler()]
    filename = os.getenv('P3_LOG_FILE', '').strip()
    if filename:
        path = Path(filename).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding='utf-8'))
    logging.basicConfig(level=level, handlers=handlers, force=True,
                        format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
    for name in ('httpx', 'httpcore', 'openai', 'mem0', 'posthog', 'urllib3'):
        logging.getLogger(name).setLevel(logging.CRITICAL)


@dataclass(frozen=True)
class Settings:
    """Configuration shared by the live Tavily, OpenAI, and mem0 clients."""

    openai_key: str
    model: str
    base_url: str
    embedding_key: str
    embedding_model: str
    embedding_base_url: str
    tavily_key: str
    database_url: str
    dimensions: int
    results: int
    news_days: int
    timeout: int
    source_chars: int
    max_output: int
    collection: str
    workspace: str

    @classmethod
    def from_env(cls) -> Settings:
        """Fail before paid research when required credentials or settings are missing."""
        load_environment()
        dsn = required('P3_DATABASE_URL')
        if not dsn.startswith(('postgresql://', 'postgres://')):
            raise ResearchError('P3_DATABASE_URL must use PostgreSQL.')
        return cls(required('OPENAI_API_KEY'), required('OPENAI_MODEL'), required('OPENAI_BASE_URL'),
            os.getenv('OPENAI_EMBEDDING_API_KEY') or required('OPENAI_API_KEY'),
            required('OPENAI_EMBEDDING_MODEL'),
            os.getenv('OPENAI_EMBEDDING_BASE_URL') or required('OPENAI_BASE_URL'),
            required('TAVILY_API_KEY'), dsn, integer('P3_EMBEDDING_DIMS', 1536, maximum=2000),
            integer('P3_SEARCH_RESULTS', 5, maximum=10), integer('P3_NEWS_DAYS', 30, maximum=365),
            integer('P3_TIMEOUT_SECONDS', 60, maximum=300), integer('P3_SOURCE_CHARS', 2500, maximum=10000),
            integer('P3_MAX_OUTPUT_TOKENS', 3000, maximum=12000),
            os.getenv('P3_MEMORY_COLLECTION', 'project3_research'), os.getenv('P3_WORKSPACE', 'market-research'))
