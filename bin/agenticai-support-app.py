#!/usr/bin/env python3
"""Streamlit customer support chatbot with hybrid Pinecone retrieval."""

from __future__ import annotations

import math
import os
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
# Make the shared package available when this file is launched directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.common import (
    load_environment,
    iter_support_files,
    read_source,
    split_text,
    tokenize,
    stable_vector_id,
)
from openai import OpenAI
from pinecone import Pinecone


load_environment()

APP_TITLE = "RemindMe Support"
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 512
DEFAULT_NAMESPACE = "__default__"
DEFAULT_TOP_K = 6
DEFAULT_CONFIDENCE_THRESHOLD = 0.38
DEFAULT_SEMANTIC_WEIGHT = 0.65
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
TEXT_SUFFIXES = {".json", ".md", ".txt", ".csv", ".yaml", ".yml"}


@dataclass(frozen=True)
class CorpusChunk:
    source_path: Path
    chunk_index: int
    text: str

    @property
    def vector_id(self) -> str:
        """Return a stable ID for this local corpus chunk.

        Called by keyword_search when producing local keyword hits and by
        merge_hits when combining local keyword results with Pinecone semantic
        results.
        """
        return stable_vector_id(self.source_path, self.chunk_index, self.text)


@dataclass
class RetrievalHit:
    vector_id: str
    source: str
    text: str
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    combined_score: float = 0.0


@st.cache_data(show_spinner=False)
def load_corpus() -> list[CorpusChunk]:
    """Load and cache local support corpus chunks.

    Called by main on each Streamlit rerun. Streamlit caches the result until
    source files or code dependencies change.
    """
    chunks: list[CorpusChunk] = []
    for path in iter_support_files(TEXT_SUFFIXES):
        text = read_source(path)
        if not text:
            continue
        for index, chunk in enumerate(split_text(text, CHUNK_SIZE, CHUNK_OVERLAP)):
            chunks.append(CorpusChunk(path, index, chunk))
    return chunks


@st.cache_data(show_spinner=False)
def build_keyword_index(chunks: Sequence[CorpusChunk]) -> dict[str, Any]:
    """Build cached BM25-style keyword statistics for corpus chunks.

    Called by answer_question before keyword_search. It calls tokenize for each
    chunk and returns document frequency, term frequency, and length metadata.
    """
    tokenized_docs = [tokenize(chunk.text) for chunk in chunks]
    doc_freq: Counter[str] = Counter()
    term_freqs: list[Counter[str]] = []
    doc_lengths: list[int] = []

    for tokens in tokenized_docs:
        counts = Counter(tokens)
        term_freqs.append(counts)
        doc_lengths.append(len(tokens))
        doc_freq.update(counts.keys())

    avg_doc_length = sum(doc_lengths) / max(len(doc_lengths), 1)
    return {
        "doc_freq": doc_freq,
        "term_freqs": term_freqs,
        "doc_lengths": doc_lengths,
        "avg_doc_length": avg_doc_length,
        "doc_count": len(chunks),
    }


def keyword_search(
    query: str,
    chunks: Sequence[CorpusChunk],
    keyword_index: dict[str, Any],
    top_k: int,
) -> list[RetrievalHit]:
    """Return top local keyword matches for a user query.

    Called by answer_question as the lexical half of hybrid retrieval. It calls
    tokenize for the query and uses the cached keyword index from
    build_keyword_index.
    """
    query_terms = tokenize(query)
    if not query_terms:
        return []

    scores: list[tuple[float, int]] = []
    doc_count = keyword_index["doc_count"]
    avg_doc_length = keyword_index["avg_doc_length"]
    k1 = 1.5
    b = 0.75

    for doc_index, term_counts in enumerate(keyword_index["term_freqs"]):
        score = 0.0
        doc_length = max(keyword_index["doc_lengths"][doc_index], 1)
        for term in query_terms:
            term_frequency = term_counts.get(term, 0)
            if not term_frequency:
                continue
            containing_docs = keyword_index["doc_freq"].get(term, 0)
            idf = math.log(1 + (doc_count - containing_docs + 0.5) / (containing_docs + 0.5))
            denominator = term_frequency + k1 * (1 - b + b * doc_length / avg_doc_length)
            score += idf * (term_frequency * (k1 + 1)) / denominator
        if score > 0:
            scores.append((score, doc_index))

    if not scores:
        return []

    scores.sort(reverse=True)
    max_score = scores[0][0]
    hits: list[RetrievalHit] = []
    for score, doc_index in scores[:top_k]:
        chunk = chunks[doc_index]
        hits.append(
            RetrievalHit(
                vector_id=chunk.vector_id,
                source=str(chunk.source_path),
                text=chunk.text,
                keyword_score=score / max_score if max_score else 0.0,
            )
        )
    return hits


@st.cache_resource(show_spinner=False)
def get_openai_client(api_key: str) -> OpenAI:
    """Create and cache an OpenAI client for the provided API key.

    Called by answer_question before embedding or chat completion requests.
    """
    return OpenAI(api_key=api_key)


@st.cache_resource(show_spinner=False)
def get_pinecone_index(api_key: str, index_name: str) -> Any:
    """Create and cache a Pinecone index handle.

    Called by answer_question before semantic_search queries Pinecone.
    """
    return Pinecone(api_key=api_key).Index(index_name)


def create_query_embedding(client: OpenAI, query: str, model: str, dimensions: int) -> list[float]:
    """Create an embedding vector for a user question.

    Called by semantic_search before querying Pinecone.
    """
    response = client.embeddings.create(
        model=model,
        input=query,
        dimensions=dimensions,
        encoding_format="float",
    )
    return response.data[0].embedding


def semantic_search(
    query: str,
    openai_client: OpenAI,
    pinecone_index: Any,
    namespace: str,
    embedding_model: str,
    embedding_dimensions: int,
    top_k: int,
) -> list[RetrievalHit]:
    """Return semantic matches from Pinecone for a user query.

    Called by answer_question as the semantic half of hybrid retrieval. This
    function calls create_query_embedding before querying Pinecone.
    """
    embedding = create_query_embedding(
        client=openai_client,
        query=query,
        model=embedding_model,
        dimensions=embedding_dimensions,
    )
    results = pinecone_index.query(
        vector=embedding,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )

    matches = getattr(results, "matches", None) or results.get("matches", [])
    hits: list[RetrievalHit] = []
    for match in matches:
        metadata = getattr(match, "metadata", None) or match.get("metadata", {})
        score = float(getattr(match, "score", None) or match.get("score", 0.0))
        vector_id = str(getattr(match, "id", None) or match.get("id", ""))
        text = str(metadata.get("text") or "")
        if not text:
            continue
        hits.append(
            RetrievalHit(
                vector_id=vector_id,
                source=str(metadata.get("source") or metadata.get("source_name") or "Pinecone"),
                text=text,
                semantic_score=max(0.0, min(score, 1.0)),
            )
        )
    return hits


def merge_hits(
    semantic_hits: Sequence[RetrievalHit],
    keyword_hits: Sequence[RetrievalHit],
    semantic_weight: float,
    top_k: int,
) -> list[RetrievalHit]:
    """Merge semantic and keyword hits into a ranked hybrid result set.

    Called by answer_question after semantic_search and keyword_search complete.
    The returned hits are used by should_escalate, generate_answer, and
    render_sources.
    """
    keyword_weight = 1.0 - semantic_weight
    merged: dict[str, RetrievalHit] = {}

    for hit in semantic_hits:
        merged[hit.vector_id] = hit

    for hit in keyword_hits:
        existing = merged.get(hit.vector_id)
        if existing:
            existing.keyword_score = max(existing.keyword_score, hit.keyword_score)
            if not existing.source:
                existing.source = hit.source
        else:
            merged[hit.vector_id] = hit

    for hit in merged.values():
        hit.combined_score = (
            semantic_weight * hit.semantic_score + keyword_weight * hit.keyword_score
        )

    return sorted(merged.values(), key=lambda item: item.combined_score, reverse=True)[:top_k]


def should_escalate(hits: Sequence[RetrievalHit], threshold: float) -> tuple[bool, str]:
    """Decide whether a retrieved answer should be escalated to a human.

    Called by answer_question after merge_hits. Returns both the routing decision
    and a short explanation displayed to the user when escalation occurs.
    """
    if not hits:
        return True, "No relevant support records were retrieved."

    best = hits[0].combined_score
    if best < threshold:
        return True, f"Retrieval confidence {best:.2f} is below the {threshold:.2f} threshold."

    if hits[0].semantic_score < 0.20 and hits[0].keyword_score < 0.35:
        return True, "Both semantic and keyword matches were weak."

    return False, ""


def build_context(hits: Sequence[RetrievalHit]) -> str:
    """Build numbered support context blocks for the chat model.

    Called by generate_answer to turn hybrid RetrievalHit objects into prompt
    context.
    """
    blocks = []
    for index, hit in enumerate(hits, 1):
        blocks.append(
            f"[{index}] Source: {hit.source}\n"
            f"Hybrid score: {hit.combined_score:.2f}; "
            f"semantic: {hit.semantic_score:.2f}; keyword: {hit.keyword_score:.2f}\n"
            f"{hit.text}"
        )
    return "\n\n".join(blocks)


def generate_answer(
    client: OpenAI,
    model: str,
    question: str,
    hits: Sequence[RetrievalHit],
) -> str:
    """Generate a grounded support answer from retrieved context.

    Called by answer_question when should_escalate permits an AI response. This
    function calls build_context and asks OpenAI to cite source numbers.
    """
    context = build_context(hits)
    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful RemindMe customer support assistant. "
                    "Answer only from the provided support context. If the context "
                    "does not contain the answer, say that the case should be escalated "
                    "to a human support specialist. Be concise and cite source numbers."
                ),
            },
            {
                "role": "user",
                "content": f"Support context:\n{context}\n\nCustomer question:\n{question}",
            },
        ],
    )
    return response.choices[0].message.content or ""


def get_required_setting(name: str) -> str:
    """Return a required setting from the environment.

    Called by answer_question for required OpenAI and Pinecone credentials.
    Raises RuntimeError so the Streamlit UI can display the setup problem.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


def configure_page() -> None:
    """Configure Streamlit page metadata and app-wide styling.

    Called by main before any visible app layout is rendered.
    """
    st.set_page_config(page_title=APP_TITLE, page_icon="RM", layout="wide")
    st.markdown(
        """
        <style>
        .stApp {
            background: #f7f8fa;
            color: #17202a;
        }
        .block-container {
            padding-top: 1.3rem;
            max-width: 1180px;
        }
        [data-testid="stSidebar"] {
            background: #eef1f4;
            border-right: 1px solid #d9dee6;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        .source-row {
            border: 1px solid #d9dee6;
            border-radius: 6px;
            padding: 0.65rem 0.75rem;
            margin-bottom: 0.55rem;
            background: #ffffff;
        }
        .metric-strip {
            font-size: 0.8rem;
            color: #4d5b6a;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_state() -> None:
    """Initialize Streamlit session state keys used by the chat UI.

    Called by main on every rerun before sidebar controls, chat history, or
    source panels read session state.
    """
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "last_hits" not in st.session_state:
        st.session_state.last_hits = []
    if "last_confidence" not in st.session_state:
        st.session_state.last_confidence = 0.0
    if "last_escalated" not in st.session_state:
        st.session_state.last_escalated = False


def render_sidebar(chunks: Sequence[CorpusChunk]) -> dict[str, Any]:
    """Render retrieval controls and return selected runtime settings.

    Called by main after load_corpus. The returned settings are passed to
    answer_question when the user submits a prompt.
    """
    st.sidebar.title("Controls")
    top_k = st.sidebar.slider("Results", min_value=3, max_value=12, value=DEFAULT_TOP_K)
    threshold = st.sidebar.slider(
        "Escalation threshold",
        min_value=0.10,
        max_value=0.80,
        value=DEFAULT_CONFIDENCE_THRESHOLD,
        step=0.01,
    )
    semantic_weight = st.sidebar.slider(
        "Semantic weight",
        min_value=0.0,
        max_value=1.0,
        value=DEFAULT_SEMANTIC_WEIGHT,
        step=0.05,
    )

    st.sidebar.divider()
    st.sidebar.metric("Local chunks", len(chunks))
    st.sidebar.metric("Last confidence", f"{st.session_state.last_confidence:.2f}")
    st.sidebar.metric("Routing", "Human" if st.session_state.last_escalated else "AI")

    if st.sidebar.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_hits = []
        st.session_state.last_confidence = 0.0
        st.session_state.last_escalated = False
        st.rerun()

    return {
        "top_k": top_k,
        "threshold": threshold,
        "semantic_weight": semantic_weight,
    }


def render_sources(hits: Sequence[RetrievalHit]) -> None:
    """Render the selected retrieval sources in the right-hand panel.

    Called by main after chat handling using the latest hits stored in
    st.session_state.
    """
    st.subheader("Sources")
    if not hits:
        st.caption("No sources selected.")
        return

    for index, hit in enumerate(hits, 1):
        preview = hit.text.replace("\n", " ")
        if len(preview) > 260:
            preview = f"{preview[:257]}..."
        st.markdown(
            f"""
            <div class="source-row">
                <strong>[{index}] {hit.source}</strong>
                <div class="metric-strip">
                    hybrid {hit.combined_score:.2f} · semantic {hit.semantic_score:.2f} · keyword {hit.keyword_score:.2f}
                </div>
                <div>{preview}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def answer_question(question: str, settings: dict[str, Any], chunks: Sequence[CorpusChunk]) -> str:
    """Answer one user question using hybrid retrieval and OpenAI.

    Called by main when a chat prompt is submitted. This function loads settings,
    gets cached clients, calls build_keyword_index, keyword_search,
    semantic_search, merge_hits, should_escalate, and generate_answer.
    """
    openai_api_key = get_required_setting("OPENAI_API_KEY")
    pinecone_api_key = get_required_setting("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME") or os.getenv("PINECONE_INDEX")
    if not index_name:
        raise RuntimeError("Missing PINECONE_INDEX_NAME in .env")

    openai_client = get_openai_client(openai_api_key)
    pinecone_index = get_pinecone_index(pinecone_api_key, index_name)
    embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions = int(
        os.getenv("OPENAI_EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS))
    )
    chat_model = os.getenv("OPENAI_CHAT_MODEL", DEFAULT_CHAT_MODEL)
    namespace = os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE)

    keyword_index = build_keyword_index(chunks)
    keyword_hits = keyword_search(question, chunks, keyword_index, settings["top_k"])
    semantic_hits = semantic_search(
        query=question,
        openai_client=openai_client,
        pinecone_index=pinecone_index,
        namespace=namespace,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        top_k=settings["top_k"],
    )
    hits = merge_hits(
        semantic_hits=semantic_hits,
        keyword_hits=keyword_hits,
        semantic_weight=settings["semantic_weight"],
        top_k=settings["top_k"],
    )

    st.session_state.last_hits = hits
    st.session_state.last_confidence = hits[0].combined_score if hits else 0.0
    escalated, reason = should_escalate(hits, settings["threshold"])
    st.session_state.last_escalated = escalated

    if escalated:
        return (
            "I’m going to escalate this to a human support specialist instead of guessing. "
            f"{reason}"
        )

    return generate_answer(
        client=openai_client,
        model=chat_model,
        question=question,
        hits=hits,
    )


def main() -> None:
    """Run the Streamlit chatbot application.

    Called by the module entrypoint when Streamlit executes this script.
    Coordinates page setup, state initialization, corpus loading, sidebar
    rendering, chat message rendering, question answering, and source display.
    """
    configure_page()
    initialize_state()

    chunks = load_corpus()
    settings = render_sidebar(chunks)

    header_col, status_col = st.columns([0.72, 0.28], vertical_alignment="center")
    with header_col:
        st.title(APP_TITLE)
    with status_col:
        status = "Human review" if st.session_state.last_escalated else "AI ready"
        st.metric("Status", status)

    chat_col, source_col = st.columns([0.64, 0.36], gap="large")

    with chat_col:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Ask about tickets, FAQs, or manuals")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Searching support records"):
                    try:
                        answer = answer_question(prompt, settings, chunks)
                    except Exception as chat_lookup_error:
                        answer = f"I can’t complete the lookup right now. {chat_lookup_error}"
                        st.session_state.last_escalated = True
                    st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.rerun()

    with source_col:
        render_sources(st.session_state.last_hits)


if __name__ == "__main__":
    main()
