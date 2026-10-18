#!/usr/bin/env python3
"""Generate 20 random test questions from the RemindMe local corpus."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_OUTPUT_FILE = Path("20Questions.md")
DEFAULT_QUESTION_COUNT = 20
DEFAULT_CONTEXT_BUDGET = 18000
DEFAULT_RANDOM_SEED = None
TEXT_SUFFIXES = {".csv", ".html", ".json", ".md", ".rst", ".txt", ".yaml", ".yml"}
WHITESPACE_RE = re.compile(r"\s+")


class QuestionGenerationError(RuntimeError):
    """Raised when test question generation cannot continue."""


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    text: str


def parse_args() -> argparse.Namespace:
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="Generate random RAG test questions from RemindMe* files."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="Markdown file to write. Defaults to 20Questions.md.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_QUESTION_COUNT,
        help="Number of questions to generate.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_CHAT_MODEL", DEFAULT_MODEL),
        help="OpenAI chat model to use.",
    )
    parser.add_argument(
        "--context-budget",
        type=int,
        default=DEFAULT_CONTEXT_BUDGET,
        help="Approximate character budget for sampled source context.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="Optional random seed for repeatable source sampling.",
    )
    return parser.parse_args()


def iter_remindme_files() -> Iterable[Path]:
    for directory in sorted(Path(".").glob("RemindMe*")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def compact_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def read_source(path: Path) -> SourceDocument:
    raw_text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if path.suffix.lower() == ".json":
        try:
            raw_text = json.dumps(json.loads(raw_text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return SourceDocument(path=path, text=compact_text(raw_text))


def load_sources() -> list[SourceDocument]:
    sources = []
    for path in iter_remindme_files():
        source = read_source(path)
        if source.text:
            sources.append(source)
    return sources


def sample_context(
    sources: Sequence[SourceDocument],
    context_budget: int,
    rng: random.Random,
) -> str:
    if context_budget <= 0:
        raise QuestionGenerationError("--context-budget must be greater than zero.")

    shuffled_sources = list(sources)
    rng.shuffle(shuffled_sources)
    per_source_budget = max(600, context_budget // max(len(shuffled_sources), 1))

    blocks: list[str] = []
    remaining = context_budget
    for source in shuffled_sources:
        if remaining <= 0:
            break

        text = source.text
        excerpt_size = min(len(text), per_source_budget, remaining)
        if len(text) > excerpt_size:
            start = rng.randint(0, max(len(text) - excerpt_size, 0))
            excerpt = text[start : start + excerpt_size].strip()
        else:
            excerpt = text

        block = f"Source: {source.path}\nExcerpt: {excerpt}"
        blocks.append(block)
        remaining -= len(block)

    return "\n\n".join(blocks)


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise QuestionGenerationError(f"Missing {name}. Add it to .env.")
    return value


def extract_questions(response_text: str) -> list[str]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise QuestionGenerationError(f"OpenAI did not return valid JSON: {exc}") from exc

    questions = data.get("questions")
    if not isinstance(questions, list):
        raise QuestionGenerationError("OpenAI JSON response did not include a questions list.")

    clean_questions = []
    for item in questions:
        if isinstance(item, str):
            question = item.strip()
        elif isinstance(item, dict):
            question = str(item.get("question") or "").strip()
        else:
            continue

        if question:
            clean_questions.append(question)

    return clean_questions


def generate_questions(
    client: OpenAI,
    model: str,
    context: str,
    count: int,
) -> list[str]:
    if count <= 0:
        raise QuestionGenerationError("--count must be greater than zero.")

    response = client.chat.completions.create(
        model=model,
        temperature=0.9,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate evaluation questions for a RAG customer support "
                    "system. Return only JSON with a 'questions' array of strings."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Create exactly {count} varied, realistic questions that a user, "
                    "support agent, manager, or auditor might ask about the RemindMe "
                    "support tickets, FAQs, product manuals, policies, and operational "
                    "data below. Mix easy lookup questions, troubleshooting questions, "
                    "policy questions, and cross-document questions. Do not answer the "
                    "questions.\n\n"
                    f"RemindMe source context:\n{context}"
                ),
            },
        ],
    )

    response_text = response.choices[0].message.content or ""
    questions = extract_questions(response_text)
    if len(questions) != count:
        raise QuestionGenerationError(
            f"Expected {count} questions, but OpenAI returned {len(questions)}."
        )
    return questions


def write_markdown(path: Path, questions: Sequence[str], model: str) -> None:
    lines = [
        "# 20 Test Questions",
        "",
        "Generated from the local `RemindMe*` files for testing the Pinecone/OpenAI RAG application.",
        "",
        f"Model: `{model}`",
        "",
    ]
    for index, question in enumerate(questions, 1):
        lines.append(f"{index}. {question}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    sources = load_sources()
    if not sources:
        raise QuestionGenerationError("No readable files found in RemindMe* directories.")

    rng = random.Random(args.seed)
    context = sample_context(sources, args.context_budget, rng)
    openai_api_key = get_required_env("OPENAI_API_KEY")
    questions = generate_questions(
        client=OpenAI(api_key=openai_api_key),
        model=args.model,
        context=context,
        count=args.count,
    )
    write_markdown(args.output, questions, args.model)
    print(f"Wrote {len(questions)} questions to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QuestionGenerationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
