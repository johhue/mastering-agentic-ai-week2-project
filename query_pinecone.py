#!/usr/bin/env python3
"""List files that have been upserted to a Pinecone index.

The script loads Pinecone credentials from .env, lists vector IDs in the target
namespace, fetches their metadata, and summarizes distinct source files.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pinecone import Pinecone


DEFAULT_NAMESPACE = "__default__"
DEFAULT_BATCH_SIZE = 100


class QueryPineconeError(RuntimeError):
    """Raised when Pinecone inspection cannot continue."""


@dataclass
class SourceSummary:
    source: str
    source_name: str = ""
    source_dir: str = ""
    vector_ids: list[str] = field(default_factory=list)
    chunk_indexes: set[int] = field(default_factory=set)


def parse_args() -> argparse.Namespace:
    load_dotenv(override=True)

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


def batched(items: Sequence[str], batch_size: int) -> Iterator[Sequence[str]]:
    if batch_size <= 0:
        raise ValueError("batch-size must be greater than zero")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise QueryPineconeError(f"Missing {name}. Add it to .env.")
    return value


def get_field(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def flatten_list_response(response: Any) -> Iterator[str]:
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
    ids: list[str] = []

    try:
        for page in index.list(namespace=namespace):
            ids.extend(flatten_list_response(page))
    except Exception as exc:
        raise QueryPineconeError(
            f"Could not list vectors in namespace '{namespace}': {exc}"
        ) from exc

    return sorted(set(ids))


def fetch_metadata(index: Any, ids: Sequence[str], namespace: str) -> dict[str, dict[str, Any]]:
    response = index.fetch(ids=list(ids), namespace=namespace)
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
    stats = index.describe_index_stats()
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
    print(f"\nNamespace: {namespace}")
    print(f"Vectors: {vector_count}")
    print(f"Files: {len(summaries)}")

    if not summaries:
        print("No vectors found.")
        return

    for index, summary in enumerate(summaries, 1):
        chunk_count = len(summary.vector_ids)
        chunk_label = "chunk" if chunk_count == 1 else "chunks"
        print(f"{index:>2}. {summary.source} ({chunk_count} {chunk_label})")

        if show_chunks:
            chunk_indexes = sorted(summary.chunk_indexes)
            if chunk_indexes:
                print(f"    chunk indexes: {chunk_indexes}")
            for vector_id in summary.vector_ids:
                print(f"    vector: {vector_id}")


def main() -> int:
    args = parse_args()
    pinecone_api_key = get_required_env("PINECONE_API_KEY")
    if not args.index:
        raise QueryPineconeError("Missing PINECONE_INDEX_NAME. Add it to .env.")

    pinecone_client = Pinecone(api_key=pinecone_api_key)
    index = pinecone_client.Index(args.index)

    namespaces = list_namespaces(index) if args.all_namespaces else [args.namespace]
    if not namespaces:
        print("No namespaces found.")
        return 0

    total_vectors = 0
    total_files = 0
    print(f"Index: {args.index}")
    for namespace in namespaces:
        summaries, vector_count = summarize_sources(index, namespace, args.batch_size)
        total_vectors += vector_count
        total_files += len(summaries)
        print_summary(namespace, summaries, vector_count, args.show_chunks)

    print(f"\nTotal vectors: {total_vectors}")
    print(f"Total file entries: {total_files}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (QueryPineconeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
