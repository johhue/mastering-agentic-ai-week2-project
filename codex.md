# Codex Build Log

## Streamlit application progress logging

`comparison_app/app.py` logs at INFO before page setup, appearance/mode controls,
connection indicators, form handling, service initialization, graph streaming,
session persistence, PDF creation, report sections, downloads and client cleanup.
Briefing rendering includes run IDs; DEBUG adds per-profile rendering and empty
session details. Stage messages describe completed graph updates before UI display;
the pipeline itself logs before executing graph stages. New messages omit input,
credentials and report bodies. Unexpected errors log their type rather than raw
exception text. Existing shared logging settings and research behavior are retained.

## Pipeline progress logging

`comparison_app/pipeline.py` logs at INFO before every graph node and before
search, extraction, citation validation, memory read/write and briefing assembly.
Run IDs correlate concurrent branches; numbered profile searches identify pricing,
features/positioning and news, and competitor indices identify profile progress.
WARNING records partial-search and unverified-profile fallbacks. Logs contain
operation names and counts rather than prompts, credentials or evidence bodies.
The pipeline uses a module logger and leaves logging configuration to callers.
The CLI's LOG_LEVEL/P3_DEBUG controls continue to apply. `profile` accepts an
optional run_id for correlation while preserving standalone calls.

## Comparison research CLI

`bin/agenticai-comparison-research` invokes the current `ResearchPipeline.graph`
with max_concurrency=2. Usage: `uv run python bin/agenticai-comparison-research
"Company (website)"`. It uses `utils.config.Settings`, the live Tavily/OpenAI
services, and `comparison_app.memory_mem0.SharedMemoryMem0`. Configure live
credentials in root .env. --demo runs the same graph with fictional services,
marks output demo=true, and needs no API credentials. Default output is JSON
on stdout; --format markdown renders the same briefing as the UI.
--output PATH exclusively creates a file before API calls, preserving existing
files and surfacing invalid destinations before paid work. Failed runs can leave
an empty file. Logs use shared utils.common logging (LOGGER_FILE, LOG_LEVEL),
with P3_DEBUG enabling debug. Live clients close even after graph failures.

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

## Comparison application — hosted mem0.ai

The current app lives in `comparison_app/`; launchers are in `bin/`.
Rebuild with Python 3.12+, `uv sync`, and the root `.env.example` settings in
root `.env`. Configure OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL,
TAVILY_API_KEY and MEM0_API_KEY. Run `./bin/agenticai-comparison-app.sh`.
Full configuration and architecture: `comparison_app/README.md`.

`bin/agenticai-mem0-store` stores JSON objects from a file or stdin using the
same hosted memory adapter. Example: `uv run python bin/agenticai-mem0-store
data.json --company Acme`. Only MEM0_API_KEY is required for this CLI; it prints
the generated run ID and stored memory IDs. Optional flags: --kind and --run-id.

Inspect hosted contents with `uv run python bin/agenticai-mem0-query`.
It lists a page of full JSON records using MemoryClient.get_all; --company
applies SharedMemory.namespace with P3_WORKSPACE, --run-id and --kind add filters.
Without --company, user_id=* lists across the API key's project. --page and
--page-size control pagination (default 1/20, maximum page size 100).
--memory-id fetches one record directly. This command never writes or deletes
memories. MEM0_API_KEY is its only required credential; root .env, timeout,
safe logging, debugging and client cleanup follow the storage CLI conventions.

PostgreSQL is no longer required. SharedMemory uses hosted mem0.MemoryClient,
with bounded HTTP timeouts, sanitized request logging and telemetry disabled.
Exact artifacts live in metadata with infer=False. Company/workspace hashes,
run IDs and artifact kinds isolate agent handoffs. Do not restore the old
PostgresHistory injection, pgvector setup or Compose startup requirements.
Existing local databases and volumes are not deleted or migrated.

Keep functions documented, wrap service failures in safe ResearchError messages,
and log operations without credentials. P3_DEBUG=true or LOG_LEVEL=DEBUG enables
debugging; P3_LOG_FILE selects optional file output. Keep configuration in .env.
Offline demo requires no credentials. Run `uv run python -m unittest discover
-s comparison_app/tests -v` for offline graph, hosted HTTP contract, UI and PDF
checks. No live service calls are required for these tests.

## Current comparison application documentation (2026-10-25)

The current operational references are comparison_app/README.md and
comparison_app/docs/{architecture,configuration,runbook}.md. Architecture includes
Mermaid network and graph diagrams. These documents supersede older build-history
CLI examples: the current comparison-research command hardcodes Toyota and
filesystem memory, with argument parsing and report-file export commented out.
The UI selects MEMORY_METHOD. The filesystem backend uses /var/tmp filenames;
hosted memory uses SharedMemoryMem0. The memory CLI imports are currently stale.
Use the Python Streamlit launcher directly for its configured final listener.
The configuration reference records LOGGER_FILE/P3_LOG_FILE and environment-load
precedence differences. Future builders should reconcile these known limitations
before relying on older intended behavior. Documentation does not change runtime
code, migrate data or execute live services.
