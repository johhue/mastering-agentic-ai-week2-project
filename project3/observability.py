"""Credential-safe agent messages and outbound HTTP request logging."""
from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)


def safe_text(value: object) -> str:
    """Bound messages and redact configured credentials before writing one log line."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    for key, secret in os.environ.items():
        if secret and any(word in key.upper() for word in ('KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'DATABASE_URL')):
            text = text.replace(secret, '[REDACTED]')
    return text[:12000]


def safe_url(value: object) -> str:
    """Keep endpoint paths while removing user information, query values and fragments."""
    try:
        parts = urlsplit(str(value))
        if parts.scheme not in ('https', 'http') or not parts.hostname:
            return '[non-HTTP endpoint]'
        host = parts.hostname
        if ':' in host:
            host = f'[{host}]'
        if parts.port:
            host += f':{parts.port}'
        return safe_text(urlunsplit((parts.scheme, host, parts.path, '', '')))
    except (ValueError, TypeError):
        return '[invalid endpoint]'


def log_request(request) -> None:
    """Observe actual SDK HTTP requests, including retries, without headers or bodies."""
    log.info('External HTTP request method=%s url=%s', request.method, safe_url(request.url))


def log_response(response) -> None:
    """Record the status of an external response without exposing its contents."""
    log.info('External HTTP response status=%s url=%s', response.status_code, safe_url(response.request.url))


def observe_client(client) -> None:
    """Attach request/response hooks to an OpenAI SDK synchronous HTTP client."""
    transport = getattr(client, '_client', None)
    hooks = getattr(transport, 'event_hooks', None)
    if isinstance(hooks, dict):
        if log_request not in hooks.setdefault('request', []):
            hooks['request'].append(log_request)
        if log_response not in hooks.setdefault('response', []):
            hooks['response'].append(log_response)


def message(sender: str, recipient: str, summary: str, payload: object = None) -> None:
    """Log public agent communication; detailed payloads are opt-in DEBUG data."""
    log.info('Agent message %s -> %s: %s', sender, recipient, safe_text(summary))
    if payload is not None and log.isEnabledFor(logging.DEBUG):
        log.debug('Agent conversation %s -> %s: %s', sender, recipient, safe_text(payload))
