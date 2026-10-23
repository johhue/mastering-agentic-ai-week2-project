# Codex Build Log

## Shared Corpus Helpers

`project2/common.py` owns corpus directory discovery, file iteration, safe UTF-8
reading, JSON normalization, whitespace compaction, overlapping text splitting,
keyword tokenization, and deterministic vector IDs, alongside environment and
logging helpers. The scripts in `bin/` import these helpers; keep command-specific
arguments, API calls, UI, and result models in their respective scripts.

Corpus discovery uses `<repository>/data/RemindMe*`, and `.env` is loaded from
the repository root regardless of the working directory. Each script supplies
its own supported file suffixes and chunk settings. Unreadable sources are logged
and skipped; malformed JSON remains raw text. Direct Python launchers add the
repository root to the import path before importing `project2.common`.

Vector IDs preserve the existing SHA-256/UUID5 formula, including the source path.
Discovery now returns absolute paths: re-upsert into a fresh or cleared namespace
if existing vectors were generated with relative paths, so hybrid retrieval uses
matching IDs and avoids duplicate entries.

After `uv sync`, run `uv run python -m unittest discover -s tests -v` to verify
chunk boundaries, vector ID compatibility, file handling, and normalization.
Offline corpus checks found 92 ingestion/retrieval chunks and 11 question sources.

## Exception Variable Convention

Scripts under `bin/` use a distinct, descriptive variable for every bound
exception, such as `index_connection_error` or `query_cli_error`. Do not reuse
an exception variable name from an enclosing scope: Python clears an exception
binding when its handler exits. Update all references in the handler, including
log messages, formatted strings, and `raise ... from ...` chains, when renaming.
The 24 existing bindings across the six Python scripts were checked for syntax
and equivalent parsed code after accounting for these variable renames.

This document summarizes the work completed with Codex to create the RemindMe customer support AI application.

## Application Goal

We built a customer support RAG application for RemindMe. The application uses local company support data, Pinecone as the vector database, and OpenAI for embeddings and LLM answers.

The system supports:

- Uploading RemindMe support content into Pinecone
- Inspecting what files were upserted
- Asking questions from the command line
- Running a Streamlit customer support chatbot
- Combining keyword search and semantic search
- Escalating uncertain answers to a human instead of hallucinating
- Generating test questions for validating the chatbot

## Source Data

The application reads local files from the `RemindMe*` directories:

- `RemindMe Company Data/`
- `RemindMe Company Manuals/`

These directories include support tickets, customer data, employee data, software variance data, FAQs, user guides, product documentation, compliance manuals, HR policies, legal disclosures, and help desk manuals.

## Environment Configuration

The scripts load secrets and settings from `.env`.

Required values:

```bash
OPENAI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=...
```

Optional values:

```bash
OPENAI_CHAT_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=512
PINECONE_NAMESPACE=__default__
```

## Pinecone Upsert

We created `bin/agenticai-vectordb-upsert`.

This script:

- Loads `.env`
- Finds directories matching `RemindMe*`
- Reads supported text files
- Splits documents into overlapping chunks
- Embeds chunks with OpenAI
- Uses `512` embedding dimensions by default
- Upserts vectors into Pinecone
- Stores metadata such as source file, source directory, chunk index, text, and SHA-256 hash

Run it with:

```bash
uv run python upsert_to_pinecone.py
```

Dry-run mode:

```bash
uv run python upsert_to_pinecone.py --dry-run
```

The dry run loaded `92` chunks from the RemindMe data and manuals.

## Pinecone Inspection

We created `bin/agenticai-vectordb-query`.

This script connects to Pinecone and lists the source files represented by upserted vectors.

After moving the command into `bin/`, it adds the resolved repository root to
Python's import path so `project2.common` is available from any working directory.
Use the project environment (`uv sync` to install dependencies), then run
`uv run python bin/agenticai-query-pinecone` from the repository root. With the
project environment activated, the executable also supports
`./bin/agenticai-query-pinecone --help`. Batch sizes must be between 1 and 1000.
Keep credentials in the repository `.env`; set `LOG_LEVEL=DEBUG` to enable
debugging and `LOGGER_FILE` for optional file logging.
Use only the `pinecone` SDK dependency: the obsolete `pinecone-client` package
conflicts with its imports. If repairing an environment that had both installed,
run `uv sync --reinstall-package pinecone` after removing `pinecone-client`.

Run it with:

```bash
uv run python bin/agenticai-query-pinecone
```

The live verification showed:

```text
Index: huetter
Namespace: __default__
Vectors: 92
Files: 11
```

For detailed vector and chunk output:

```bash
uv run python bin/agenticai-query-pinecone --show-chunks
```

## Streamlit Chatbot

We created `bin/support_chatbot.py`.

This is the main customer support chatbot UI. It uses Streamlit and supports hybrid retrieval:

- Local keyword search over the RemindMe files
- Semantic search through Pinecone
- Weighted hybrid score merging
- OpenAI answer generation over retrieved context
- Source display with retrieval confidence
- Confidence-based escalation to a human

The chatbot avoids guessing by default. If retrieval confidence is too low, it routes the question to a human support specialist instead of inventing an answer.

## Streamlit Launcher

We created `bin/agenticai-run-chatbot.sh`.

Run the chatbot with:

```bash
./run_support_chatbot.sh
```

The default port is `8501`.

To choose another port:

```bash
STREAMLIT_PORT=8502 ./run_support_chatbot.sh
```

## Command-Line RAG Utility

We created `bin/agenticai-rag-openai-pinecone`.

This command-line utility lets a user ask a question and get an OpenAI-generated answer using Pinecone RAG context.

Example:

```bash
uv run python query_openai_pinecone.py "How do I create a reminder?" --show-sources
```

By default, hallucinations are not permitted. If Pinecone retrieval confidence is too low, the script escalates instead of answering.

To permit broader, less-grounded answers:

```bash
uv run python query_openai_pinecone.py "What should I do if reminders fail?" --allow-hallucinations
```

When hallucinations are permitted, the model is still instructed to say when an answer is not supported by retrieved sources.

## Test Question Generation

We created `bin/agenticai-generate-test-questions`.

This script:

- Reads files from the `RemindMe*` directories
- Randomly samples source context
- Calls the OpenAI LLM
- Generates exactly 20 realistic test questions
- Writes the result to `20Questions.md`

Run it with:

```bash
uv run python generate_test_questions.py
```

Optional repeatable generation:

```bash
uv run python generate_test_questions.py --seed 42
```

The generated file is `20Questions.md`, which contains questions for testing the RAG chatbot and CLI.

## OpenAI Model Listing and Usage

Run `uv run python query_openai.py --list-models` to print every model ID
returned by `GET /v1/models`, sorted alphabetically. This mode uses
`OPENAI_API_KEY` from `.env` and lists models visible to that key without
requesting billing data. No additional dependencies are needed.

Without `--list-models`, the existing organization usage report uses
`OPENAI_ADMIN_KEY`. Override either key variable with `--api-key-env NAME`.
The optional `.env` setting `OPENAI_CHAT_BASE_URL` overrides the API base URL.
Set `LOG_LEVEL=DEBUG` for debugging and `LOGGER_FILE` for file logging.
HTTP, network, malformed response, and missing credential errors are logged
and return a nonzero exit code.

## Runtime Dependencies

We updated `requirements.txt` so the project includes the needed runtime packages:

```text
openai
pinecone
python-dotenv
streamlit
```

The project also uses `uv` and the existing `pyproject.toml` / `uv.lock` environment.

## Verification

We verified the scripts with syntax checks and live runs, including:

```bash
python -m py_compile upsert_to_pinecone.py
python -m py_compile support_chatbot.py
python -m py_compile query_pinecone.py
python -m py_compile query_openai_pinecone.py
python -m py_compile generate_test_questions.py
```

We also verified:

- `upsert_to_pinecone.py --dry-run` loaded `92` chunks
- `bin/support_chatbot.py` loaded the local corpus
- `bin/agenticai-vectordb-query` found `92` vectors and `11` files in Pinecone
- `bin/agenticai-rag-openai-pinecone` successfully answered a live RAG question
- `bin/agenticai-generate-test-questions` created `20Questions.md`

## Final Workflow

1. Put secrets in `.env`.
2. Upload RemindMe data to Pinecone:

   ```bash
   uv run python upsert_to_pinecone.py
   ```

3. Confirm uploaded files:

   ```bash
   uv run python bin/agenticai-query-pinecone
   ```

4. Launch the Streamlit chatbot:

   ```bash
   ./run_support_chatbot.sh
   ```

5. Ask terminal-based RAG questions:

   ```bash
   uv run python query_openai_pinecone.py "How do I create a reminder?" --show-sources
   ```

6. Generate evaluation questions:

   ```bash
   uv run python generate_test_questions.py
   ```

The result is a working OpenAI + Pinecone customer support RAG application with both UI and CLI access, inspection tooling, test-question generation, and hallucination-aware fallback behavior.

## Project3 — Multi-agent Market Research

`project3/` implements Competitive Signal, a Streamlit competitor-analysis system
with LangGraph, Tavily as its primary web/news source, and open-source mem0 shared
between three specialist agents and an orchestrator. This is independent of the
project2 RemindMe application. The full architecture, source limitations, database
adapter contract, configuration reference and rebuild steps are in
`project3/README.md`.

From the repository root, rebuild and launch with:

```bash
uv sync
docker compose --env-file .env -f project3/compose.yaml -p project3-research up -d --wait
./project3/start-streamlit.sh
```

Add the settings in `project3/.env.example` to the root `.env`, preserving existing
OpenAI credentials. `TAVILY_API_KEY` is required for live research. Use the existing
`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, and separate embedding key,
model and base URL settings. The endpoint must support Chat Completions structured
outputs. `P3_DATABASE_URL` connects both vectors and audit history to PostgreSQL.
Compose uses a separate pgvector-enabled PostgreSQL 17 server on localhost port
5434 and a persistent volume. Its password is generated in `.env` for this local
installation; when rebuilding from the example, replace the placeholder password
and update the client URL to match. Restart Streamlit after changing credentials.

Agent 1 queries Tavily, selects exactly three distinct, relevant competitors and
saves discovery to mem0. Agent 2 queries that shared memory and researches pricing,
features/positioning, and recent news for every competitor. Agent 3 researches the
subject company. Agents 2 and 3 run as parallel graph nodes and save typed artifacts
back to mem0. The orchestrator joins both branches, retrieves all saved profiles,
and compiles a cited, structured briefing. PDF and JSON downloads share the same
underlying artifact. A normal run makes 13 Tavily queries plus bounded retries;
model and embedding calls use the configured providers. No paid call is made until
the user explicitly submits a live run.

Mem0 is pinned at `mem0ai==2.2.1`. Its pgvector provider is configured explicitly;
there is no Qdrant fallback. Since that SDK hardcodes a SQLite history backend,
`project3/memory.py` injects a PostgreSQL history adapter only during construction,
under a lock, and restores the SDK module immediately. The real-SDK integration
test fails if any SQLite connection is attempted. Revalidate that interface before
upgrading mem0. Artifacts use `infer=False`, compact embedded descriptors and exact
JSON metadata to preserve company names, citations and source data. Retrieval
filters include workspace/company namespace, run ID, and artifact kind. New runs
do not reuse stale research from previous runs.

The application labels facts, inferences and unknowns. Source IDs are checked
against supplied evidence; news claims must cite dated news inside the configured
recency window. Dates from ISO and RFC news results are supported. These are
provenance checks rather than automatic proof of each claim; users should verify
commercial decisions against original sources. Search failures become collection
notes or unknown profile fields. Failed discovery, compilation or mandatory mem0
handoffs stop the run without pretending to complete the research. Logs record
stages, counts, memory operations and exports without API keys or research bodies.
Set `P3_DEBUG=true` or `LOG_LEVEL=DEBUG` in `.env` for debugging.

For an offline review, select Offline demo: it runs the same graph using fictional
companies and explicitly labeled in-process test doubles, not live services or
persistent memory. The example PDF is generated under `project3/output/pdf/` and
page renderings are under `project3/tmp/pdfs/`; both directories are ignored by Git.
PDF export uses ReportLab with escaped content, wrapped comparison cells, source
references and page numbers. Configure optional Unicode TTF fonts for non-Latin
writing systems. Render every sample page and inspect it after layout changes.

Validation commands:

```bash
uv run python -m unittest discover -s project3/tests -v
P3_TEST_POSTGRES=true uv run python -m unittest project3.tests.test_postgres_memory -v
```

Offline tests exercise all agent handoffs, three-competitor validation, source-ID
rejection, run/company isolation, missing research, bounded retries, news freshness,
Streamlit submission and PDF download, PDF text coverage, and markup escaping.
The opt-in test uses actual mem0 + PostgreSQL/pgvector with fake embeddings and a
mocked model, so it spends no API credits. It checks persistence through a fresh
client and PostgreSQL audit/message history. Test cleanup deletes only IDs returned
by its own writes and its unique message scope; it never drops a vector collection.

Project3 verification completed on 2026-10-22 (local date): all 13 tests passed
with the PostgreSQL integration enabled. The real mem0 client recovered exact
artifacts through a fresh client, kept runs/companies isolated, and never opened
SQLite. Streamlit demo submission and PDF download passed. Every project3
function was checked for a docstring, and the three-page fictional sample PDF was
rendered for visual inspection. Live Tavily/OpenAI research was not exercised:
`TAVILY_API_KEY` is not configured. No API credits were spent during verification.
The isolated PostgreSQL/pgvector service is running on localhost port 5434.

### Project3 Streamlit startup

`project3/start-streamlit.sh` resolves the repository root and runs
`project3/start_streamlit.py` using `.venv/bin/python`. The Python launcher loads
root `.env` before starting Streamlit, configures application logging, validates
`P3_STREAMLIT_PORT` (1-65535), and uses `os.execv` to preserve signal handling.
The configured port is **5555**, and `P3_STREAMLIT_ADDRESS` defaults to
`127.0.0.1`. Explicit `--server.port` and `--server.address` arguments prevent
unrelated Streamlit environment settings from overriding the selected listener.
Run `./project3/start-streamlit.sh`; open `http://127.0.0.1:5555` and stop with
Ctrl-C. The launcher logs startup/failure without exposing .env secrets.

Startup verification: launched the shell script from `/private/tmp` to confirm
working-directory independence. Streamlit bound to `127.0.0.1:5555`, and
`GET /_stcore/health` returned `ok`. Shell syntax and whitespace checks passed.

### Project3 photo background and per-user dark mode

`project3/appearance.py` adds a sidebar Dark theme toggle and local photo
background, without modifying process-wide Streamlit theme settings. The
photorealistic futuristic data-center asset is bundled at
`project3/assets/futuristic-it-background.png`. It was generated with the built-in
ImageGen tool; the full prompt and provenance are in `project3/assets/README.md`.
No external image host or image-generation call is used at app runtime.

Appearance defaults are in root `.env`: `P3_DEFAULT_THEME=light`,
`P3_BACKGROUND_ENABLED=true`, and
`P3_BACKGROUND_IMAGE=project3/assets/futuristic-it-background.png`.
The sidebar switch overrides the default for that session and remembers the
choice in the `appearance` query parameter. Switching themes preserves the
briefing, run ID and PDF rather than starting another paid research run. Other
sessions retain their own settings. The photo is embedded as a cached, validated
PNG/JPEG/WebP data URI, with an 8 MB limit; missing/invalid files fall back to the
solid theme and emit a safe warning. Light and dark CSS palettes style the
sidebar, input controls, tabs, status panels, metrics, buttons and report table.
The comparison is rendered as an HTML table so its colors follow the page theme.
Recheck Streamlit CSS component selectors when upgrading the framework.

The theme regression test switches light/dark after generating a demo briefing,
checks that the report/PDF are unchanged, and confirms a separate session starts
with its own default. No research API calls are made by appearance changes.

Appearance verification: both Streamlit UI tests passed, including dark/light
switching with unchanged briefing and PDF and a separate session's default.
The running port-5555 health endpoint returned `ok`. Browser visual inspection
was unavailable in this session; the generated background asset was inspected.

### Project3 agent observability (2026-10-22)

`project3/observability.py` logs public agent messages and credential-sanitized
outbound HTTP URLs. Pipeline handoffs include run IDs; DEBUG adds bounded JSON
research artifacts, task/context/evidence and validated responses. This exposes
agent communication and progress, not private reasoning. Configure `P3_DEBUG=true`
and `P3_LOG_FILE` in root `.env`; restart the Streamlit launcher to reload settings.
OpenAI and mem0 embedding/LLM clients use HTTPX request/response hooks; Tavily logs
each search attempt and labels returned evidence links separately. URL query,
fragment, user information and all headers/bodies are excluded from HTTP logs.
No new dependencies or credentials are needed. PostgreSQL/memory configuration is
unchanged. Verify with `.venv/bin/python -m unittest discover -s project3/tests`;
observability tests use a fake HTTP transport and no API credits.
