#!/usr/bin/env python3
"""Ask OpenAI a question using Pinecone RAG context."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone


DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 512
DEFAULT_NAMESPACE = "__default__"
DEFAULT_TOP_K = 6
DEFAULT_CONFIDENCE_THRESHOLD = 0.30


class QueryError(RuntimeError):
    """Raised when the RAG query cannot be completed."""


@dataclass(frozen=True)
class RetrievalHit:
    source: str
    text: str
    score: float


def parse_args() -> argparse.Namespace:
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="Ask a question using OpenAI plus RAG context from Pinecone."
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Question to ask. If omitted, the script prompts for one.",
    )
    parser.add_argument(
        "--allow-hallucinations",
        action="store_true",
        help=(
            "Permit the model to answer beyond retrieved Pinecone context. "
            "Without this flag, low-confidence retrieval escalates instead of guessing."
        ),
    )
    parser.add_argument(
        "--index",
        default=os.getenv("PINECONE_INDEX_NAME") or os.getenv("PINECONE_INDEX"),
        help="Pinecone index name. Defaults to PINECONE_INDEX_NAME or PINECONE_INDEX.",
    )
    parser.add_argument(
        "--namespace",
        default=os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE),
        help="Pinecone namespace to query.",
    )
    parser.add_argument(
        "--chat-model",
        default=os.getenv("OPENAI_CHAT_MODEL", DEFAULT_CHAT_MODEL),
        help="OpenAI chat model.",
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
        help="Embedding dimensions to request from OpenAI.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Number of Pinecone matches to retrieve.",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=DEFAULT_CONFIDENCE_THRESHOLD,
        help="Minimum top Pinecone score required when hallucinations are not permitted.",
    )
    parser.add_argument(
        "--show-sources",
        action="store_true",
        help="Print retrieved sources and scores after the answer.",
    )
    return parser.parse_args()


def get_question(args: argparse.Namespace) -> str:
    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()
    if not question:
        raise QueryError("A question is required.")
    return question


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise QueryError(f"Missing {name}. Add it to .env.")
    return value


def get_field(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def create_query_embedding(
    client: OpenAI,
    question: str,
    model: str,
    dimensions: int,
) -> list[float]:
    response = client.embeddings.create(
        model=model,
        input=question,
        dimensions=dimensions,
        encoding_format="float",
    )
    return response.data[0].embedding


def query_pinecone(
    index: Any,
    embedding: Sequence[float],
    namespace: str,
    top_k: int,
) -> list[RetrievalHit]:
    results = index.query(
        vector=list(embedding),
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    matches = get_field(results, "matches", []) or []

    hits: list[RetrievalHit] = []
    for match in matches:
        metadata = get_field(match, "metadata", {}) or {}
        text = str(metadata.get("text") or "").strip()
        if not text:
            continue

        hits.append(
            RetrievalHit(
                source=str(metadata.get("source") or metadata.get("source_name") or "Pinecone"),
                text=text,
                score=float(get_field(match, "score", 0.0) or 0.0),
            )
        )

    return hits


def build_context(hits: Sequence[RetrievalHit]) -> str:
    blocks = []
    for index, hit in enumerate(hits, 1):
        blocks.append(
            f"[{index}] Source: {hit.source}\n"
            f"Relevance score: {hit.score:.3f}\n"
            f"{hit.text}"
        )
    return "\n\n".join(blocks)


def should_refuse_answer(
    hits: Sequence[RetrievalHit],
    confidence_threshold: float,
    allow_hallucinations: bool,
) -> tuple[bool, str]:
    if allow_hallucinations:
        return False, ""
    if not hits:
        return True, "No Pinecone RAG context was retrieved."
    if hits[0].score < confidence_threshold:
        return (
            True,
            f"Top retrieval score {hits[0].score:.3f} is below threshold "
            f"{confidence_threshold:.3f}.",
        )
    return False, ""


def generate_answer(
    client: OpenAI,
    model: str,
    question: str,
    hits: Sequence[RetrievalHit],
    allow_hallucinations: bool,
) -> str:
    context = build_context(hits) or "No Pinecone context was retrieved."
    if allow_hallucinations:
        system_prompt = (
            "You are a helpful customer support assistant. Use the Pinecone RAG "
            "context when it is relevant. If the context is incomplete, you may use "
            "general reasoning, but clearly say when an answer is not supported by "
            "the retrieved sources."
        )
    else:
        system_prompt = (
            "You are a careful customer support assistant. Answer only from the "
            "Pinecone RAG context. If the answer is not contained in the context, "
            "say you do not have enough information and recommend escalation to a "
            "human support specialist. Cite source numbers like [1]."
        )

    response = client.chat.completions.create(
        model=model,
        temperature=0.2 if allow_hallucinations else 0.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Pinecone RAG context:\n{context}\n\nQuestion:\n{question}",
            },
        ],
    )
    return response.choices[0].message.content or ""


def print_sources(hits: Sequence[RetrievalHit]) -> None:
    print("\nSources")
    if not hits:
        print("- No sources retrieved.")
        return
    for index, hit in enumerate(hits, 1):
        print(f"- [{index}] {hit.source} (score: {hit.score:.3f})")


def main() -> int:
    args = parse_args()
    question = get_question(args)
    openai_api_key = get_required_env("OPENAI_API_KEY")
    pinecone_api_key = get_required_env("PINECONE_API_KEY")
    if not args.index:
        raise QueryError("Missing PINECONE_INDEX_NAME. Add it to .env or pass --index.")
    if args.top_k <= 0:
        raise QueryError("--top-k must be greater than zero.")

    openai_client = OpenAI(api_key=openai_api_key)
    pinecone_index = Pinecone(api_key=pinecone_api_key).Index(args.index)

    embedding = create_query_embedding(
        client=openai_client,
        question=question,
        model=args.embedding_model,
        dimensions=args.embedding_dimensions,
    )
    hits = query_pinecone(
        index=pinecone_index,
        embedding=embedding,
        namespace=args.namespace,
        top_k=args.top_k,
    )

    refuse, reason = should_refuse_answer(
        hits=hits,
        confidence_threshold=args.confidence_threshold,
        allow_hallucinations=args.allow_hallucinations,
    )
    if refuse:
        print("I do not have enough reliable RAG context to answer without guessing.")
        print(f"Reason: {reason}")
        print("Escalation: Please route this question to a human support specialist.")
        if args.show_sources:
            print_sources(hits)
        return 0

    answer = generate_answer(
        client=openai_client,
        model=args.chat_model,
        question=question,
        hits=hits,
        allow_hallucinations=args.allow_hallucinations,
    )
    print(answer)

    if args.show_sources:
        print_sources(hits)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QueryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
