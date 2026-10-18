#!/usr/bin/env python3
"""List files that have been upserted to a Pinecone index.

The script loads Pinecone credentials from .env, lists vector IDs in the target
namespace, fetches their metadata, and summarizes distinct source files.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from common import batched, configure_logging, get_field, get_required_env, load_environment
from pinecone import Pinecone, PineconeException


DEFAULT_NAMESPACE = "__default__"
DEFAULT_BATCH_SIZE = 100
LOGGER = logging.getLogger(__name__)


class QueryPineconeError(RuntimeError):
    """Raised when Pinecone inspection cannot continue."""


@dataclass
class SourceSummary:
    source: str
    source_name: str = ""
    source_dir: str = ""
    vector_ids: list[str] = field(default_factory=list)
    chunk_indexes: set[int] = field(default_factory=set)


def create_pinecone_index(api_key: str, index_name: str) -> Any:
    """Create a Pinecone index handle and normalize connection failures.

    Called by main after validating the Pinecone API key and index name.
    """
    try:
        pinecone_client = Pinecone(api_key=api_key)
        return pinecone_client.Index(index_name)
    except PineconeException as exc:
        raise QueryPineconeError(
            f"Could not connect to Pinecone index '{index_name}': {exc}"
        ) from exc
    except Exception as exc:
        raise QueryPineconeError(
            f"Unexpected error while creating Pinecone index '{index_name}': {exc}"
        ) from exc


def parse_args() -> argparse.Namespace:
    """Load .env values and parse command-line arguments.

    Called by main to determine the target index, namespace, and output options.
    """
    load_environment()

    parser = argparse.ArgumentParser(
        description="List source files represented by vectors in a Pinecone index."
    )
    parser.add_argument(
        "--index",
        default=os.getenv("PINECONE_INDEX_NAME") or os.getenv("PINECONE_INDEX"),
        help="Pinecone index name. Defaults to PINECONE_INDEX_NAME or PINECONE_INDEX.",
    )
    parser.add_argument(
        "--namespace",
        default=os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE),
        help="Pinecone namespace to inspect.",
    )
    parser.add_argument(
        "--all-namespaces",
        action="store_true",
        help="Inspect every namespace reported by Pinecone index stats.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of vector IDs to fetch at a time.",
    )
    parser.add_argument(
        "--show-chunks",
        action="store_true",
        help="Print vector IDs and chunk indexes under each source file.",
    )
    return parser.parse_args()


def flatten_list_response(response: Any) -> Iterator[str]:
    """Flatten Pinecone list response pages into vector ID strings.

    Called by list_vector_ids and recursively by itself for nested response data.
    """
    if response is None:
        return

    if isinstance(response, str):
        yield response
        return

    if isinstance(response, dict):
        vectors = response.get("vectors")
        if vectors is not None:
            yield from flatten_list_response(vectors)
            return
        vector_ids = response.get("ids")
        if vector_ids is not None:
            yield from flatten_list_response(vector_ids)
            return

    if hasattr(response, "vectors"):
        yield from flatten_list_response(getattr(response, "vectors"))
        return
    if hasattr(response, "ids"):
        yield from flatten_list_response(getattr(response, "ids"))
        return

    if isinstance(response, Iterable):
        for item in response:
            if isinstance(item, str):
                yield item
            else:
                yield from flatten_list_response(item)


def list_vector_ids(index: Any, namespace: str) -> list[str]:
    """List unique vector IDs in a Pinecone namespace.

    Called by summarize_sources before fetching metadata for each vector ID.
    """
    ids: list[str] = []

    try:
        for page in index.list(namespace=namespace):
            ids.extend(flatten_list_response(page))
    except PineconeException as exc:
        raise QueryPineconeError(
            f"Could not list vectors in namespace '{namespace}': {exc}"
        ) from exc
    except Exception as exc:
        raise QueryPineconeError(
            f"Unexpected error while listing vectors in namespace '{namespace}': {exc}"
        ) from exc

    return sorted(set(ids))


def fetch_metadata(index: Any, ids: Sequence[str], namespace: str) -> dict[str, dict[str, Any]]:
    """Fetch metadata for vector IDs from a Pinecone namespace.

    Called by summarize_sources for each batch of vector IDs.
    """
    try:
        response = index.fetch(ids=list(ids), namespace=namespace)
    except PineconeException as exc:
        raise QueryPineconeError(
            f"Could not fetch metadata for {len(ids)} vectors in namespace '{namespace}': {exc}"
        ) from exc
    except Exception as exc:
        raise QueryPineconeError(
            f"Unexpected error while fetching metadata in namespace '{namespace}': {exc}"
        ) from exc

    vectors = get_field(response, "vectors", {}) or {}

    metadata_by_id: dict[str, dict[str, Any]] = {}
    for vector_id, vector in vectors.items():
        metadata = get_field(vector, "metadata", {}) or {}
        metadata_by_id[str(vector_id)] = dict(metadata)
    return metadata_by_id


def summarize_sources(
    index: Any,
    namespace: str,
    batch_size: int,
) -> tuple[list[SourceSummary], int]:
    """Build per-source summaries from vectors stored in a namespace.

    Called by main once for each namespace selected for inspection.
    """
    vector_ids = list_vector_ids(index, namespace)
    summaries: dict[str, SourceSummary] = {}

    for id_batch in batched(vector_ids, batch_size):
        metadata_by_id = fetch_metadata(index, id_batch, namespace)
        for vector_id in id_batch:
            metadata = metadata_by_id.get(vector_id, {})
            source = str(metadata.get("source") or "(missing source metadata)")
            summary = summaries.setdefault(source, SourceSummary(source=source))
            summary.vector_ids.append(vector_id)

            if metadata.get("source_name"):
                summary.source_name = str(metadata["source_name"])
            if metadata.get("source_dir"):
                summary.source_dir = str(metadata["source_dir"])
            if metadata.get("chunk_index") is not None:
                try:
                    summary.chunk_indexes.add(int(metadata["chunk_index"]))
                except (TypeError, ValueError):
                    pass

    return sorted(summaries.values(), key=lambda item: item.source), len(vector_ids)


def list_namespaces(index: Any) -> list[str]:
    """Return namespace names reported by Pinecone index stats.

    Called by main when the --all-namespaces option is enabled.
    """
    try:
        stats = index.describe_index_stats()
    except PineconeException as exc:
        raise QueryPineconeError(f"Could not list Pinecone namespaces: {exc}") from exc
    except Exception as exc:
        raise QueryPineconeError(
            f"Unexpected error while listing Pinecone namespaces: {exc}"
        ) from exc

    namespaces = get_field(stats, "namespaces", {}) or {}
    if isinstance(namespaces, dict):
        return sorted(str(name) for name in namespaces.keys())
    return []


def print_summary(
    namespace: str,
    summaries: Sequence[SourceSummary],
    vector_count: int,
    show_chunks: bool,
) -> None:
    """Log a human-readable summary for one namespace.

    Called by main after summarize_sources returns source and vector counts.
    """
    LOGGER.info("\nNamespace: %s", namespace)
    LOGGER.info("Vectors: %s", vector_count)
    LOGGER.info("Files: %s", len(summaries))

    if not summaries:
        LOGGER.info("No vectors found.")
        return

    for index, summary in enumerate(summaries, 1):
        chunk_count = len(summary.vector_ids)
        chunk_label = "chunk" if chunk_count == 1 else "chunks"
        LOGGER.info("%2d. %s (%s %s)", index, summary.source, chunk_count, chunk_label)

        if show_chunks:
            chunk_indexes = sorted(summary.chunk_indexes)
            if chunk_indexes:
                LOGGER.info("    chunk indexes: %s", chunk_indexes)
            for vector_id in summary.vector_ids:
                LOGGER.info("    vector: %s", vector_id)


def main() -> int:
    """Run the query CLI and return the process exit code.

    Called by the module entrypoint when this script is executed directly.
    """
    configure_logging()
    args = parse_args()
    pinecone_api_key = get_required_env("PINECONE_API_KEY", QueryPineconeError)
    if not args.index:
        raise QueryPineconeError("Missing PINECONE_INDEX_NAME. Add it to .env.")

    index = create_pinecone_index(pinecone_api_key, args.index)

    namespaces = list_namespaces(index) if args.all_namespaces else [args.namespace]
    if not namespaces:
        LOGGER.info("No namespaces found.")
        return 0

    total_vectors = 0
    total_files = 0
    LOGGER.info("Index: %s", args.index)
    for namespace in namespaces:
        summaries, vector_count = summarize_sources(index, namespace, args.batch_size)
        total_vectors += vector_count
        total_files += len(summaries)
        print_summary(namespace, summaries, vector_count, args.show_chunks)

    LOGGER.info("\nTotal vectors: %s", total_vectors)
    LOGGER.info("Total file entries: %s", total_files)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        LOGGER.error("Interrupted.")
        raise SystemExit(130) from None
    except (QueryPineconeError, ValueError) as exc:
        LOGGER.error("Error: %s", exc)
        raise SystemExit(1) from exc
