#!/usr/bin/env python3
"""Read RemindMe files, embed them with OpenAI, and upsert to Pinecone.

Required .env values:
    OPENAI_API_KEY=...
    PINECONE_API_KEY=...
    PINECONE_INDEX_NAME=...

Optional .env values:
    OPENAI_EMBEDDING_MODEL=text-embedding-3-small
    OPENAI_EMBEDDING_DIMENSIONS=512
    PINECONE_NAMESPACE=__default__
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from openai import OpenAI
from pinecone import Pinecone


DEFAULT_INPUT_GLOB = "RemindMe*"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 512
DEFAULT_NAMESPACE = "__default__"
T = TypeVar("T")
TEXT_SUFFIXES = {
    ".csv",
    ".html",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".text",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


class UpsertError(RuntimeError):
    """Raised when the upsert cannot continue."""


@dataclass(frozen=True)
class DocumentChunk:
    """A single chunk of text and its source location."""

    source_path: Path
    chunk_index: int
    text: str

    @property
    def vector_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.source_path}:{self.chunk_index}:{self.text}".encode("utf-8")
        ).hexdigest()
        return str(uuid.uuid5(uuid.NAMESPACE_URL, digest))


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ."""

    if not path.exists():
        return

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"Skipping malformed .env line {line_number}", file=sys.stderr)
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser(
        description="Embed files in RemindMe* directories and upsert them to Pinecone."
    )
    parser.add_argument(
        "--input-glob",
        default=DEFAULT_INPUT_GLOB,
        help="Directory glob to scan. Defaults to RemindMe*.",
    )
    parser.add_argument(
        "--index",
        default=os.getenv("PINECONE_INDEX_NAME") or os.getenv("PINECONE_INDEX"),
        help="Pinecone index name. Defaults to PINECONE_INDEX_NAME or PINECONE_INDEX.",
    )
    parser.add_argument(
        "--namespace",
        default=os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE),
        help="Pinecone namespace to upsert into.",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        help="OpenAI embedding model.",
    )
    parser.add_argument(
        "--embedding-dimensions",
        type=int,
        default=int(
            os.getenv("OPENAI_EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS))
        ),
        help="Embedding dimensions requested from OpenAI.",
    )
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--upsert-batch-size", type=int, default=100)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and chunk files without embedding or upserting.",
    )
    return parser.parse_args()


def find_input_dirs(input_glob: str) -> list[Path]:
    dirs = [path for path in sorted(Path(".").glob(input_glob)) if path.is_dir()]
    return [path for path in dirs if path.name.startswith("RemindMe")]


def iter_text_files(input_dirs: Sequence[Path]) -> Iterator[Path]:
    for input_dir in input_dirs:
        for path in sorted(input_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError as exc:
        print(f"Skipping unreadable file {path}: {exc}", file=sys.stderr)
        return ""


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> Iterator[str]:
    if chunk_size <= 0:
        raise ValueError("chunk-size must be greater than zero")
    if chunk_overlap < 0:
        raise ValueError("chunk-overlap must be zero or greater")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk-overlap must be smaller than chunk-size")

    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end == len(text):
            break
        start = end - chunk_overlap


def load_chunks(
    input_dirs: Sequence[Path],
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for path in iter_text_files(input_dirs):
        text = read_text(path)
        if not text:
            continue
        for chunk_index, chunk in enumerate(split_text(text, chunk_size, chunk_overlap)):
            chunks.append(DocumentChunk(path, chunk_index, chunk))
    return chunks


def batched(items: Sequence[T], batch_size: int) -> Iterator[Sequence[T]]:
    if batch_size <= 0:
        raise ValueError("batch size must be greater than zero")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def embed_texts(
    client: OpenAI,
    texts: Sequence[str],
    model: str,
    dimensions: int,
) -> list[list[float]]:
    try:
        response = client.embeddings.create(
            model=model,
            input=list(texts),
            dimensions=dimensions,
            encoding_format="float",
        )
    except Exception as exc:
        raise UpsertError(f"Failed to create OpenAI embeddings: {exc}") from exc

    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


def build_vectors(
    chunks: Sequence[DocumentChunk],
    embeddings: Sequence[Sequence[float]],
) -> list[dict[str, Any]]:
    vectors: list[dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        vectors.append(
            {
                "id": chunk.vector_id,
                "values": list(embedding),
                "metadata": {
                    "source": str(chunk.source_path),
                    "source_name": chunk.source_path.name,
                    "source_dir": chunk.source_path.parent.name,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                },
            }
        )
    return vectors


def validate_environment(args: argparse.Namespace) -> tuple[str, str, str]:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    pinecone_api_key = os.getenv("PINECONE_API_KEY")

    missing = []
    if not openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not pinecone_api_key:
        missing.append("PINECONE_API_KEY")
    if not args.index:
        missing.append("PINECONE_INDEX_NAME")
    if missing:
        raise UpsertError(f"Missing required .env values: {', '.join(missing)}")

    return openai_api_key, pinecone_api_key, args.index


def upsert_chunks(
    chunks: Sequence[DocumentChunk],
    openai_client: OpenAI,
    pinecone_client: Pinecone,
    index_name: str,
    namespace: str,
    embedding_model: str,
    embedding_dimensions: int,
    embedding_batch_size: int,
    upsert_batch_size: int,
) -> int:
    index = pinecone_client.Index(index_name)
    uploaded = 0

    for chunk_batch in batched(chunks, embedding_batch_size):
        embeddings = embed_texts(
            client=openai_client,
            texts=[chunk.text for chunk in chunk_batch],
            model=embedding_model,
            dimensions=embedding_dimensions,
        )
        vectors = build_vectors(chunk_batch, embeddings)

        for vector_batch in batched(vectors, upsert_batch_size):
            index.upsert(vectors=list(vector_batch), namespace=namespace)
            uploaded += len(vector_batch)
            print(f"Upserted {uploaded}/{len(chunks)} chunks")

    return uploaded


def main() -> int:
    args = parse_args()

    input_dirs = find_input_dirs(args.input_glob)
    if not input_dirs:
        raise UpsertError(f"No RemindMe directories found for glob: {args.input_glob}")

    chunks = load_chunks(input_dirs, args.chunk_size, args.chunk_overlap)
    if not chunks:
        print("No supported text files found.")
        return 0

    print(
        f"Loaded {len(chunks)} chunks from "
        f"{', '.join(str(path) for path in input_dirs)}"
    )
    if args.dry_run:
        return 0

    openai_api_key, pinecone_api_key, index_name = validate_environment(args)
    uploaded = upsert_chunks(
        chunks=chunks,
        openai_client=OpenAI(api_key=openai_api_key),
        pinecone_client=Pinecone(api_key=pinecone_api_key),
        index_name=index_name,
        namespace=args.namespace,
        embedding_model=args.embedding_model,
        embedding_dimensions=args.embedding_dimensions,
        embedding_batch_size=args.embedding_batch_size,
        upsert_batch_size=args.upsert_batch_size,
    )

    print(
        f"Done. Upserted {uploaded} chunks to index '{index_name}' "
        f"in namespace '{args.namespace}'."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UpsertError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
