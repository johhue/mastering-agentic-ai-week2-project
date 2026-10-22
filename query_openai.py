#!/usr/bin/env python3
"""List available OpenAI models or report organization spend and token usage.

OpenAI exposes organization costs and usage through admin endpoints. The API
does not expose a universal account bill limit or token quota, so this script
reports those as unavailable unless you provide local monthly limits with
OPENAI_MONTHLY_BILL_LIMIT_USD or OPENAI_MONTHLY_TOKEN_BUDGET.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from common import configure_logging, get_required_env, load_environment


API_BASE_URL = "https://api.openai.com/v1"
DEFAULT_BUCKET_WIDTH = "1d"
LOGGER = logging.getLogger(__name__)


class OpenAIUsageError(RuntimeError):
    """Raised when OpenAI usage or cost data cannot be retrieved."""


def parse_args() -> argparse.Namespace:
    """Load .env values and parse command-line arguments.

    Called by main to determine the reporting window and optional local limits.
    """
    load_environment()

    parser = argparse.ArgumentParser(
        description="List OpenAI models or show organization costs and token usage."
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all models available to OPENAI_API_KEY instead of reporting usage.",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="API key variable (default: OPENAI_API_KEY for models, OPENAI_ADMIN_KEY for usage).",
    )
    parser.add_argument(
        "--start-time",
        type=int,
        default=None,
        help="Unix start time for the report. Defaults to the start of this UTC month.",
    )
    parser.add_argument(
        "--end-time",
        type=int,
        default=None,
        help="Unix end time for the report. Defaults to now.",
    )
    parser.add_argument(
        "--monthly-bill-limit-usd",
        type=Decimal,
        default=parse_optional_decimal(os.getenv("OPENAI_MONTHLY_BILL_LIMIT_USD")),
        help=(
            "Optional local monthly USD bill limit. Defaults to "
            "OPENAI_MONTHLY_BILL_LIMIT_USD."
        ),
    )
    parser.add_argument(
        "--monthly-token-budget",
        type=int,
        default=parse_optional_int(os.getenv("OPENAI_MONTHLY_TOKEN_BUDGET")),
        help=(
            "Optional local monthly token budget. Defaults to "
            "OPENAI_MONTHLY_TOKEN_BUDGET."
        ),
    )
    return parser.parse_args()


def parse_optional_decimal(value: str | None) -> Decimal | None:
    """Parse an optional decimal environment value.

    Called by parse_args when setting the default monthly bill limit.
    """
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise OpenAIUsageError(f"Invalid decimal value: {value}") from exc


def parse_optional_int(value: str | None) -> int | None:
    """Parse an optional integer environment value.

    Called by parse_args when setting the default monthly token budget.
    """
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise OpenAIUsageError(f"Invalid integer value: {value}") from exc


def current_month_start() -> int:
    """Return the Unix timestamp for the start of the current UTC month.

    Called by main when no explicit --start-time is provided.
    """
    now = datetime.now(UTC)
    return int(datetime(now.year, now.month, 1, tzinfo=UTC).timestamp())


def current_time() -> int:
    """Return the current Unix timestamp in UTC.

    Called by main when no explicit --end-time is provided.
    """
    return int(datetime.now(UTC).timestamp())


def get_json(api_key: str, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Issue a GET request to an OpenAI API endpoint and return JSON.

    Called by paginated_get for each costs or usage page.
    """
    query = urlencode({key: value for key, value in params.items() if value is not None})
    base_url = (os.getenv("OPENAI_CHAT_BASE_URL") or API_BASE_URL).rstrip("/")
    url = f"{base_url}{path}" + (f"?{query}" if query else "")
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    LOGGER.info("Attempting OpenAI URL: %s", url)
    LOGGER.debug("Sending OpenAI GET request to %s", path)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = read_error_detail(exc)
        raise OpenAIUsageError(f"OpenAI API request failed ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise OpenAIUsageError(f"Could not reach OpenAI API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAIUsageError(f"OpenAI API returned invalid JSON: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise OpenAIUsageError(f"Could not read OpenAI API response: {exc}") from exc


def fetch_models(api_key: str) -> list[dict[str, Any]]:
    """Return all models visible to the API key, sorted by model identifier."""
    payload = get_json(api_key, "/models", {})
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise OpenAIUsageError("OpenAI models response is missing a model list.")
    models = payload["data"]
    if any(
        not isinstance(model, dict) or not isinstance(model.get("id"), str)
        for model in models
    ):
        raise OpenAIUsageError("OpenAI models response contains an invalid model.")
    LOGGER.info("Retrieved %d available OpenAI models.", len(models))
    return sorted(models, key=lambda model: model["id"])


def read_error_detail(error: HTTPError) -> str:
    """Return the most useful message from an HTTP error response.

    Called by get_json when OpenAI returns a non-2xx response.
    """
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error.reason

    error_value = payload.get("error")
    if isinstance(error_value, dict):
        message = error_value.get("message")
        if message:
            return str(message)
    return str(payload)


def paginated_get(
    api_key: str,
    path: str,
    params: Mapping[str, Any],
) -> Iterator[dict[str, Any]]:
    """Yield pages from a paginated OpenAI organization endpoint.

    Called by fetch_costs and fetch_completions_usage.
    """
    page: str | None = None
    while True:
        payload = get_json(api_key, path, {**params, "page": page})
        yield payload

        if not payload.get("has_more"):
            return
        page = payload.get("next_page")
        if not page:
            return


def fetch_costs(api_key: str, start_time: int, end_time: int) -> Decimal:
    """Return total organization costs for a time range.

    Called by main to report month-to-date spend.
    """
    total = Decimal("0")
    params = {
        "start_time": start_time,
        "end_time": end_time,
        "bucket_width": DEFAULT_BUCKET_WIDTH,
        "limit": 180,
    }
    for page in paginated_get(api_key, "/organization/costs", params):
        for bucket in page.get("data", []):
            for result in bucket.get("results", []):
                amount = result.get("amount", {})
                total += Decimal(str(amount.get("value", 0)))
    return total


def fetch_completions_usage(
    api_key: str,
    start_time: int,
    end_time: int,
) -> dict[str, int]:
    """Return aggregated completions token usage for a time range.

    Called by main to report month-to-date token consumption.
    """
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cached_tokens": 0,
        "num_model_requests": 0,
    }
    params = {
        "start_time": start_time,
        "end_time": end_time,
        "bucket_width": DEFAULT_BUCKET_WIDTH,
        "limit": 31,
    }
    for page in paginated_get(api_key, "/organization/usage/completions", params):
        for bucket in page.get("data", []):
            for result in bucket.get("results", []):
                add_usage_result(totals, result)
    return totals


def add_usage_result(totals: dict[str, int], result: Mapping[str, Any]) -> None:
    """Add one usage result object into aggregate totals.

    Called by fetch_completions_usage for each bucket result returned by OpenAI.
    """
    for key in totals:
        totals[key] += int(result.get(key) or 0)


def format_money(value: Decimal) -> str:
    """Format a USD decimal for display.

    Called by print_report for spend and remaining bill limit values.
    """
    return f"${value.quantize(Decimal('0.01'))}"


def print_report(
    start_time: int,
    end_time: int,
    total_cost: Decimal,
    usage: Mapping[str, int],
    monthly_bill_limit_usd: Decimal | None,
    monthly_token_budget: int | None,
) -> None:
    """Log the final OpenAI billing and token usage report.

    Called by main after retrieving costs and usage from OpenAI.
    """
    total_tokens = usage["input_tokens"] + usage["output_tokens"]
    LOGGER.info("OpenAI organization usage report")
    LOGGER.info("Window: %s to %s", format_time(start_time), format_time(end_time))
    LOGGER.info("")
    LOGGER.info("Month-to-date cost: %s", format_money(total_cost))

    if monthly_bill_limit_usd is None:
        LOGGER.info(
            "Bill limit: unavailable from the OpenAI API "
            "(set OPENAI_MONTHLY_BILL_LIMIT_USD to compute remaining spend)."
        )
    else:
        remaining = monthly_bill_limit_usd - total_cost
        LOGGER.info("Bill limit: %s", format_money(monthly_bill_limit_usd))
        LOGGER.info("Bill limit remaining: %s", format_money(remaining))

    LOGGER.info("")
    LOGGER.info("Completions input tokens: %s", f"{usage['input_tokens']:,}")
    LOGGER.info("Completions output tokens: %s", f"{usage['output_tokens']:,}")
    LOGGER.info("Cached input tokens: %s", f"{usage['input_cached_tokens']:,}")
    LOGGER.info("Completions total tokens: %s", f"{total_tokens:,}")
    LOGGER.info("Model requests: %s", f"{usage['num_model_requests']:,}")

    if monthly_token_budget is None:
        LOGGER.info(
            "Tokens left: unavailable from the OpenAI API "
            "(set OPENAI_MONTHLY_TOKEN_BUDGET to compute against your own budget)."
        )
    else:
        LOGGER.info("Token budget: %s", f"{monthly_token_budget:,}")
        LOGGER.info("Tokens left: %s", f"{monthly_token_budget - total_tokens:,}")


def format_time(timestamp: int) -> str:
    """Format a Unix timestamp as an ISO UTC time.

    Called by print_report for the report window.
    """
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def main() -> int:
    """Run the OpenAI billing report CLI and return the process exit code.

    Called by the module entrypoint when this script is executed directly.
    """
    configure_logging()
    args = parse_args()
    key_env = args.api_key_env or (
        "OPENAI_ADMIN_KEY" if args.list_models else "OPENAI_ADMIN_KEY"
    )
    api_key = get_required_env(
        key_env,
        OpenAIUsageError,
        f"Missing {key_env}. Add the appropriate OpenAI API key to .env.",
    )
    if args.list_models:
        for model in fetch_models(api_key):
            print(model["id"])
        return 0
    start_time = args.start_time or current_month_start()
    end_time = args.end_time or current_time()
    if end_time <= start_time:
        raise OpenAIUsageError("--end-time must be greater than --start-time.")

    total_cost = fetch_costs(api_key, start_time, end_time)
    usage = fetch_completions_usage(api_key, start_time, end_time)
    print_report(
        start_time=start_time,
        end_time=end_time,
        total_cost=total_cost,
        usage=usage,
        monthly_bill_limit_usd=args.monthly_bill_limit_usd,
        monthly_token_budget=args.monthly_token_budget,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        LOGGER.error("Interrupted.")
        raise SystemExit(130) from None
    except OpenAIUsageError as exc:
        LOGGER.error("Error: %s", exc)
        raise SystemExit(1) from exc
