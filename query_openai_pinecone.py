#!/usr/bin/env python3
"""Ask OpenAI a question using Pinecone RAG context."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from common import (
    configure_logging,
    get_field,
    get_int_field,
    get_required_env,
    load_environment,
)
from openai import OpenAI
from pinecone import Pinecone


DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 512
DEFAULT_NAMESPACE = "__default__"
DEFAULT_TOP_K = 6
DEFAULT_CONFIDENCE_THRESHOLD = 0.30
LOGGER = logging.getLogger(__name__)


class QueryError(RuntimeError):
    """Raised when the RAG query cannot be completed."""


@dataclass(frozen=True)
class RetrievalHit:
    source: str
    text: str
    score: float


@dataclass(frozen=True)
class TokenUsage:
    label: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class EmbeddingResult:
    embedding: list[float]
    usage: TokenUsage


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    usage: TokenUsage


def parse_args() -> argparse.Namespace:
    """Parse CLI options and load .env-backed defaults.

    Called by main before credentials, Pinecone settings, and OpenAI model
    settings are validated.
    """
    load_environment()

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
        help="OpenAI chat model. Defaults to OPENAI_CHAT_MODEL.",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        help="OpenAI embedding model. Defaults to OPENAI_EMBEDDING_MODEL.",
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging for retrieval and OpenAI request details.",
    )
    return parser.parse_args()


def get_question(args: argparse.Namespace) -> str:
    """Return the question from CLI arguments or an interactive prompt.

    Called by main after parse_args. Raises QueryError when no question is
    available from either source.
    """
    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()
    if not question:
        raise QueryError("A question is required.")
    LOGGER.debug("Question captured: chars=%s words=%s", len(question), len(question.split()))
    return question


def usage_from_embedding_response(response: Any) -> TokenUsage:
    """Extract token usage from an OpenAI embedding response.

    Called by create_query_embedding after the embeddings endpoint returns.
    Returns zeroed usage when the SDK response does not include usage data.
    """
    usage = get_field(response, "usage", None)
    if usage is None:
        LOGGER.debug("Embedding response did not include usage metadata.")
        return TokenUsage(label="Embedding")

    prompt_tokens = get_int_field(usage, "prompt_tokens")
    total_tokens = get_int_field(usage, "total_tokens") or prompt_tokens
    LOGGER.debug(
        "Parsed embedding usage: prompt_tokens=%s total_tokens=%s",
        prompt_tokens,
        total_tokens,
    )
    return TokenUsage(
        label="Embedding",
        input_tokens=prompt_tokens,
        total_tokens=total_tokens,
    )


def usage_from_chat_response(response: Any) -> TokenUsage:
    """Extract prompt, completion, and total tokens from a chat response.

    Called by generate_answer after the Chat Completions response returns.
    Returns zeroed usage when the SDK response does not include usage data.
    """
    usage = get_field(response, "usage", None)
    if usage is None:
        LOGGER.debug("Chat completion response did not include usage metadata.")
        return TokenUsage(label="Chat completion")

    token_usage = TokenUsage(
        label="Chat completion",
        input_tokens=get_int_field(usage, "prompt_tokens"),
        output_tokens=get_int_field(usage, "completion_tokens"),
        total_tokens=get_int_field(usage, "total_tokens"),
    )
    LOGGER.debug(
        "Parsed chat usage: prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        token_usage.input_tokens,
        token_usage.output_tokens,
        token_usage.total_tokens,
    )
    return token_usage


def create_query_embedding(
    client: OpenAI,
    question: str,
    model: str,
    dimensions: int,
) -> EmbeddingResult:
    """Create an embedding vector for the user's question.

    Called by main before querying Pinecone. This function also calls
    usage_from_embedding_response so the final CLI summary can include embedding
    token usage.
    """
    LOGGER.debug(
        "Creating embedding with model=%s dimensions=%s question_chars=%s",
        model,
        dimensions,
        len(question),
    )
    LOGGER.info(
        "Attempting OpenAI embedding request: URL=%s/embeddings model=%s",
        str(client.base_url).rstrip("/"),
        model,
    )
    response = client.embeddings.create(
        model=model,
        input=question,
        dimensions=dimensions,
        encoding_format="float",
    )
    embedding = response.data[0].embedding
    usage = usage_from_embedding_response(response)
    LOGGER.debug(
        "Embedding created: vector_dimensions=%s total_tokens=%s",
        len(embedding),
        usage.total_tokens,
    )
    return EmbeddingResult(embedding=embedding, usage=usage)


def query_pinecone(
    index: Any,
    embedding: Sequence[float],
    namespace: str,
    top_k: int,
) -> list[RetrievalHit]:
    """Retrieve matching Pinecone records for an embedding vector.

    Called by main after create_query_embedding. Converts Pinecone response
    objects or mappings into RetrievalHit instances used by refusal checks and
    answer generation.
    """
    LOGGER.debug(
        "Querying Pinecone namespace=%s top_k=%s embedding_dimensions=%s",
        namespace,
        top_k,
        len(embedding),
    )
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
            LOGGER.debug("Skipping Pinecone match without text metadata.")
            continue

        hits.append(
            RetrievalHit(
                source=str(
                    metadata.get("source") or metadata.get("source_name") or "Pinecone"
                ),
                text=text,
                score=float(get_field(match, "score", 0.0) or 0.0),
            )
        )

    for index, hit in enumerate(hits, 1):
        LOGGER.debug(
            "Pinecone hit %s: source=%s score=%.3f text_chars=%s",
            index,
            hit.source,
            hit.score,
            len(hit.text),
        )
    LOGGER.debug(
        "Pinecone returned %s usable hits; top_score=%s",
        len(hits),
        f"{hits[0].score:.3f}" if hits else "none",
    )
    return hits


def build_context(hits: Sequence[RetrievalHit]) -> str:
    """Build numbered RAG context blocks from retrieved hits.

    Called by generate_answer to provide source text and relevance scores to the
    chat model.
    """
    blocks = []
    for index, hit in enumerate(hits, 1):
        blocks.append(
            f"[{index}] Source: {hit.source}\n"
            f"Relevance score: {hit.score:.3f}\n"
            f"{hit.text}"
        )
    context = "\n\n".join(blocks)
    LOGGER.debug("Built RAG context: hit_count=%s context_chars=%s", len(hits), len(context))
    return context


def should_refuse_answer(
    hits: Sequence[RetrievalHit],
    confidence_threshold: float,
    allow_hallucinations: bool,
) -> tuple[bool, str]:
    """Decide whether the script should answer or escalate.

    Called by main after query_pinecone. Returns a refusal flag and a human
    readable reason based on retrieval availability, confidence, and the
    --allow-hallucinations option.
    """
    if allow_hallucinations:
        LOGGER.debug("Refusal check bypassed because allow_hallucinations=True.")
        return False, ""
    if not hits:
        LOGGER.debug("Refusal check failed: no Pinecone hits.")
        return True, "No Pinecone RAG context was retrieved."
    if hits[0].score < confidence_threshold:
        LOGGER.debug(
            "Refusal check failed: top_score=%.3f threshold=%.3f",
            hits[0].score,
            confidence_threshold,
        )
        return (
            True,
            f"Top retrieval score {hits[0].score:.3f} is below threshold "
            f"{confidence_threshold:.3f}.",
        )
    LOGGER.debug(
        "Refusal check passed: top_score=%.3f threshold=%.3f",
        hits[0].score,
        confidence_threshold,
    )
    return False, ""


def generate_answer(
    client: OpenAI,
    model: str,
    question: str,
    hits: Sequence[RetrievalHit],
    allow_hallucinations: bool,
) -> AnswerResult:
    """Generate a final answer from retrieved Pinecone context.

    Called by main when should_refuse_answer allows the response. This function
    calls build_context and usage_from_chat_response, returning both answer text
    and token usage for the final summary.
    """
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

    LOGGER.debug(
        "Generating answer with model=%s context_chars=%s hit_count=%s",
        model,
        len(context),
        len(hits),
    )
    LOGGER.info(
        "Attempting OpenAI chat request: URL=%s/chat/completions model=%s",
        str(client.base_url).rstrip("/"),
        model,
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
    answer = response.choices[0].message.content or ""
    usage = usage_from_chat_response(response)
    LOGGER.debug(
        "Answer generated: answer_chars=%s total_tokens=%s",
        len(answer),
        usage.total_tokens,
    )
    return AnswerResult(answer=answer, usage=usage)


def print_sources(hits: Sequence[RetrievalHit]) -> None:
    """Print retrieved source names and scores for the CLI user.

    Called by main when --show-sources is provided, both for answered and
    refused queries.
    """
    LOGGER.debug("Printing sources: hit_count=%s", len(hits))
    print("\nSources")
    if not hits:
        print("- No sources retrieved.")
        return
    for index, hit in enumerate(hits, 1):
        print(f"- [{index}] {hit.source} (score: {hit.score:.3f})")


def print_token_summary(usages: Sequence[TokenUsage]) -> None:
    """Print per-request and total token usage for the CLI run.

    Called by main at the end of both answered and refused query paths.
    """
    total_input_tokens = sum(usage.input_tokens for usage in usages)
    total_output_tokens = sum(usage.output_tokens for usage in usages)
    total_tokens = sum(usage.total_tokens for usage in usages)
    LOGGER.debug(
        "Printing token summary: entries=%s input=%s output=%s total=%s",
        len(usages),
        total_input_tokens,
        total_output_tokens,
        total_tokens,
    )

    print("\nToken usage")
    for usage in usages:
        print(
            f"- {usage.label}: {usage.total_tokens:,} total "
            f"({usage.input_tokens:,} input, {usage.output_tokens:,} output)"
        )
    print(
        f"- Total: {total_tokens:,} total "
        f"({total_input_tokens:,} input, {total_output_tokens:,} output)"
    )


def main() -> int:
    """Run the OpenAI plus Pinecone RAG query CLI.

    Called by the module entrypoint when this script is executed directly.
    Coordinates parsing, logging, credentials, embedding creation, Pinecone
    retrieval, refusal handling, answer generation, and token reporting.
    """
    args = parse_args()
    configure_logging(debug=args.debug, level=logging.INFO)
    LOGGER.debug(
        "Parsed arguments: index_set=%s namespace=%s chat_model=%s embedding_model=%s "
        "embedding_dimensions=%s top_k=%s confidence_threshold=%.3f show_sources=%s "
        "allow_hallucinations=%s",
        bool(args.index),
        args.namespace,
        args.chat_model,
        args.embedding_model,
        args.embedding_dimensions,
        args.top_k,
        args.confidence_threshold,
        args.show_sources,
        args.allow_hallucinations,
    )
    question = get_question(args)
    openai_api_key = get_required_env("OPENAI_CHAT_API_KEY", QueryError)
    pinecone_api_key = get_required_env("PINECONE_API_KEY", QueryError)
    if not args.index:
        raise QueryError("Missing PINECONE_INDEX_NAME. Add it to .env or pass --index.")
    if args.top_k <= 0:
        raise QueryError("--top-k must be greater than zero.")

    LOGGER.debug("Validated required environment variables.")
    chat_client = OpenAI(
        api_key=openai_api_key,
        base_url=os.getenv("OPENAI_CHAT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None,
    )
    embedding_client = OpenAI(
        api_key=openai_api_key,
        base_url=(
            os.getenv("OPENAI_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
        ),
    )
    LOGGER.debug("Created OpenAI chat and embedding clients.")
    pinecone_index = Pinecone(api_key=pinecone_api_key).Index(args.index)
    LOGGER.debug("Created Pinecone index client for index=%s.", args.index)

    LOGGER.debug(
        "Starting RAG query: chat_model=%s embedding_model=%s namespace=%s top_k=%s",
        args.chat_model,
        args.embedding_model,
        args.namespace,
        args.top_k,
    )

    embedding_result = create_query_embedding(
        client=embedding_client,
        question=question,
        model=args.embedding_model,
        dimensions=args.embedding_dimensions,
    )
    hits = query_pinecone(
        index=pinecone_index,
        embedding=embedding_result.embedding,
        namespace=args.namespace,
        top_k=args.top_k,
    )fg
    usages = [embedding_result.usage]

    refuse, reason = should_refuse_answer(
        hits=hits,
        confidence_threshold=args.confidence_threshold,
        allow_hallucinations=args.allow_hallucinations,
    )
    LOGGER.debug("Refusal decision: refuse=%s reason=%s", refuse, reason or "none")
    if refuse:
        print("I do not have enough reliable RAG context to answer without guessing.")
        print(f"Reason: {reason}")
        print("Escalation: Please route this question to a human support specialist.")
        if args.show_sources:
            print_sources(hits)
        print_token_summary(usages)
        LOGGER.debug("Finished refused query path.")
        return 0

    answer_result = generate_answer(
        client=chat_client,
        model=args.chat_model,
        question=question,
        hits=hits,
        allow_hallucinations=args.allow_hallucinations,
    )
    usages.append(answer_result.usage)
    print(answer_result.answer)

    if args.show_sources:
        print_sources(hits)
    print_token_summary(usages)
    LOGGER.debug("Finished answered query path.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QueryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
