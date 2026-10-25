# Competitive Signal — comparison research

A Streamlit and LangGraph application that discovers three competitors, researches
pricing, features, positioning and news, and compiles a cited comparison briefing.
Live services are Tavily and an OpenAI-compatible endpoint; shared research uses
hosted mem0.ai or the current experimental filesystem adapter. No PostgreSQL
server or Docker service is required.

- [Architecture and network diagram](docs/architecture.md)
- [Operations run book](docs/runbook.md)
- [Configuration reference](docs/configuration.md)

Documentation reflects the source inspected on **2026-10-25**. The run book calls
out current launcher, CLI and memory-tool limitations; older command examples in
build history may describe behavior that is currently commented out.

## Start the interface

From the repository root, install dependencies with `uv sync`, populate root
`.env` using the [configuration reference](docs/configuration.md), then run:

```bash
uv run python bin/agenticai-comparison-app.py
```

The Python launcher serves the app at `http://127.0.0.1:5555` by default.
Choose **Offline demo** for fictional research without external calls. Live mode
requires credentials and `MEMORY_METHOD=MEM0` or `MEMORY_METHOD=FILESYSTEM`.
The shell launcher has different port behavior; see the run book.

## Command-line status

```bash
uv run python bin/agenticai-comparison-research
```

**This currently starts paid live research for Toyota using filesystem memory.**
The CLI has hardcoded values; argument parsing, demo flags, format selection and
report-file writing are commented out. It does not create the advertised
`/var/tmp/research_output.json`. Do not use older `--demo` examples as an offline
check. Use the Streamlit demo or the offline tests in the run book instead.

## Code map

| File | Responsibility |
| --- | --- |
| `app.py` | Streamlit form, backend selection, streaming progress, session state and downloads |
| `pipeline.py` | Discovery, parallel profile research, mandatory shared-memory handoffs and synthesis |
| `search_service.py` | Tavily queries, bounded retries and news-date filtering |
| `analyst_service.py`, `analyst_rules.py` | Structured model extraction and evidence instructions |
| `models.py` | Typed artifacts, input and citation validation |
| `memory_mem0.py` | Hosted `SharedMemoryMem0` adapter |
| `memory_filesystem.py` | Experimental local `SharedMemoryFileSystem` adapter |
| `demo.py` | Fictional search, analyst and memory doubles |
| `export.py` | Markdown and PDF rendering |
| `observability.py` | Public agent messages and sanitized HTTP logging |
| `appearance.py`, `assets/` | Session appearance and bundled background |
| `../utils/config.py`, `../utils/common.py` | Settings, root `.env` loading and shared logging |
| `tests/` | Offline graph, UI, export and memory contract tests |

Source references establish provenance, not independent factual verification.
Verify purchase decisions against original sources. Logs and persisted artifacts
can contain complete research content; see the run book before sharing them.
