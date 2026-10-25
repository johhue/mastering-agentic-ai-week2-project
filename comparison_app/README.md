# Competitive Signal

## Command-line research

```bash
uv run python bin/agenticai-comparison-research "Acme (https://example.com)"
uv run python bin/agenticai-comparison-research "Acme" --format markdown --output briefing.md
uv run python bin/agenticai-comparison-research "Demo" --demo --output demo.json
```

Live mode runs the same graph as Streamlit, including hosted mem0 handoffs,
and uses Tavily, OpenAI and mem0 quotas. Configure `OPENAI_API_KEY`,
`OPENAI_MODEL`, `OPENAI_BASE_URL`, `TAVILY_API_KEY` and `MEM0_API_KEY` in root
`.env`. `--demo` uses fictional companies and no external service calls.
JSON is the default output; logs go to stderr and `LOGGER_FILE` when configured.
Set `LOG_LEVEL=DEBUG` or `P3_DEBUG=true` in `.env` for debugging.
`--output` creates a new UTF-8 file; existing files are preserved. Its parent
directory must exist. A failed run may leave an empty output file; remove it
before retrying. Exit code 0 indicates success; failures return nonzero.

Streamlit market research using LangGraph, Tavily, OpenAI and hosted mem0.ai.
No PostgreSQL server, Docker service, pgvector or local database is required.

## Build and run

1. Install Python 3.12+ and run `uv sync` from the repository root.
2. Copy settings from root `.env.example` into root `.env`, preserving existing secrets.
3. Set `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `TAVILY_API_KEY`
   and `MEM0_API_KEY` (from your mem0.ai account).
4. Run `./bin/agenticai-comparison-app.sh` and open http://127.0.0.1:5555.

Offline demo uses fictional providers and makes no external calls. Live research
uses hosted services and their quotas. Restart the app after editing `.env`.

To store your own JSON object, run:

```bash
uv run python bin/agenticai-mem0-store data.json --company Acme --kind manual
```

Use `-` as the file argument to read stdin. `--run-id` optionally supplies an
existing run ID. The command prints the run ID and saved memory IDs. It requires
only `MEM0_API_KEY`; `P3_WORKSPACE` and `P3_TIMEOUT_SECONDS` are optional.

Inspect stored contents (read only):

```bash
uv run python bin/agenticai-mem0-query
uv run python bin/agenticai-mem0-query --company Acme --kind briefing
uv run python bin/agenticai-mem0-query --run-id RUN_ID --page 2 --page-size 20
uv run python bin/agenticai-mem0-query --memory-id MEMORY_ID
```

The command prints full JSON, including artifact metadata. Listings return one
page (20 records by default) with the API's count/next/previous fields. Without
`--company`, the listing covers all users accessible to the mem0 project API key;
with it, the company hash uses `P3_WORKSPACE` from `.env`. Use `--page` to browse
additional pages. Only `MEM0_API_KEY` is required. Logs go to stderr and configured
log files; JSON goes to stdout and can be redirected to a file.

## Memory and workflow

Agent 1 discovers three competitors; Agents 2 and 3 research competitors and the
subject company in parallel. All handoffs go through `SharedMemory` in
`memory_mem0.py`. The orchestrator retrieves profiles and builds a
cited briefing with PDF and JSON downloads. `search_service.py` owns Tavily searches
and structured OpenAI extraction; it does not own persistence.

Memory uses `mem0.MemoryClient` from pinned `mem0ai==2.2.1`. `infer=False`
stores compact descriptors synchronously, with exact artifacts in JSON metadata.
Reads filter by workspace/company namespace, run ID and artifact kind. Failed
writes or reads stop the handoff. Hosted mem0 manages embedding and persistence;
local embedding credentials, collection settings and database URLs are unused.
Old local database records are not migrated. Existing containers and volumes
are left untouched; retain them if you need their historical data.

## Configuration

All settings and secrets belong in root `.env`:

- `P3_WORKSPACE`: memory namespace, default `market-research`.
- `P3_SEARCH_RESULTS`: 1–10 sources per query, default 5.
- `P3_NEWS_DAYS`: news recency, default 30 days.
- `P3_TIMEOUT_SECONDS`: service timeout, default 60 seconds.
- `P3_SOURCE_CHARS`, `P3_MAX_OUTPUT_TOKENS`: evidence/output bounds.
- `P3_DEBUG=true` or `LOG_LEVEL=DEBUG`: enable debugging.
- `P3_LOG_FILE`: optional log file. Debug logs can contain research content;
  configured secrets are redacted and SDK raw logging is suppressed.
- `P3_STREAMLIT_PORT`, `P3_STREAMLIT_ADDRESS`: listener, default 5555/127.0.0.1.
- `P3_DEFAULT_THEME`, `P3_BACKGROUND_ENABLED`, `P3_BACKGROUND_IMAGE`: appearance.
- `P3_PDF_FONT_PATH`, `P3_PDF_BOLD_FONT_PATH`: optional Unicode fonts.

The sidebar theme switch preserves reports; Clear chat history clears session
results while retaining hosted memory. News requires dated sources inside the
recency window. Citation validation establishes provenance, not factual proof.
Verify commercial decisions against original sources.

## Verification

`uv run python -m unittest discover -s comparison_app/tests -v`

Tests cover the graph, hosted memory contracts with mocked HTTP, company/run
isolation, failures, citations, search freshness, PDF output and Streamlit UI.
They spend no API credits. Live credentials are not validated by offline tests.

Hosted SDK reference: https://github.com/mem0ai/mem0/blob/main/docs/migration/platform-v2-to-v3.mdx
