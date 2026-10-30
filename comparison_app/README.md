# Competitive Signal — comparison research

A Streamlit and LangGraph application that discovers three competitors, researches
pricing, features, positioning and news, and compiles a cited comparison briefing.
Live services are Tavily and an OpenAI-compatible endpoint; shared research uses
hosted mem0.ai or the current experimental filesystem adapter. No PostgreSQL
server or Docker service is required.

- [Architecture and network diagram](docs/architecture.md)
- [Operations run book](docs/runbook.md)
- [Configuration reference](docs/configuration.md)

Documentation updated on **2026-10-26**. All bin tools use `OptionParser` and
accept `--config PATH`. Precedence is environment, file, then command-line
overrides last. See [bin command conventions](../bin/README.md).

## Start the interface

From the repository root, install dependencies with `uv sync`, populate root
`.env` using the [configuration reference](docs/configuration.md), then run:

```bash
uv run python bin/agenticai-comparison-app.py
```

The Python launcher serves the app at `http://127.0.0.1:5555` by default.
Choose **Offline demo** for fictional research without external calls. Live mode
requires credentials and `MEMORY_METHOD=MEM0` or `MEMORY_METHOD=FILESYSTEM`.
The shell launcher forwards the same `--port`, `--address` and `--debug` options.

## Command-line status

```bash
uv run python bin/agenticai-comparison-research "Toyota" --memory-method MEM0 --output toyota.json
uv run python bin/agenticai-comparison-research Demo --demo --format markdown --output demo.md
```

The company is required. Live mode uses paid services and the backend selected
by `--memory-method` or `MEMORY_METHOD` (CLI fallback: FILESYSTEM). `--demo` uses
fictional services without network calls. JSON goes to stdout by default;
`--output` exclusively creates a new file. Existing output files are preserved.
Use `--help` to inspect options without running research.

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
