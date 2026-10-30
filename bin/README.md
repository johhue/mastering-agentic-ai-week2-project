# Command-line tools

Run from the repository root using `uv run python bin/<command>`, or activate the
project environment and execute the script. Every Python entry point exposes
`parse_args(argv=None)` and uses `optparse.OptionParser` through `utils.cli`:

- `-h` / `--help` prints usage and exits successfully, without
  configuring logs, validating credentials, starting servers or calling services.
- `--debug` enables application debug logging; `--no-debug` disables it.
  Boolean switches have matching `--no-...` flags to override configured values.
- `--config PATH` selects a configuration file in `.env` format. The default is
  root `.env`, or the file named by `AGENTICAI_CONFIG`.
- Long options use their full spelling; abbreviations and unknown options are
  rejected. Argument/type/usage errors exit with code 2 before external work.
- Precedence, from lowest to highest, is **environment → configuration file →
  command line**. Built-in defaults are used when no source provides a value.
  Environment numeric conversion is deferred until parsing, so malformed runtime
  settings do not prevent help from displaying.
- Logging and credential validation happen after parsing. Results retain each
  tool's existing output convention; JSON-producing tools write JSON to stdout.

The shared helper handles parser construction, positive integers, nonempty text,
logging and Streamlit startup. Do not configure logging or create service clients
at module scope in an executable. Register flags with `parser.add_option()`.
Use `parse_options(parser, argv)` to validate and return `optparse.Values`, and
declare positional inputs through that helper. Native `parser.parse_args()`
retains OptionParser's `(options, remaining_args)` return contract. Preserve
existing command names and flags.

## Configuration files and environment variables

Every option and positional input has a canonical configuration/environment key:
`AGENTICAI_<COMMAND>_<DESTINATION>`. Remove `agenticai-` and `.py` from the command
name and replace hyphens with underscores; uppercase all parts. For example:

| Input | Canonical key |
| --- | --- |
| comparison-research company | `AGENTICAI_COMPARISON_RESEARCH_COMPANY` |
| comparison-research --demo | `AGENTICAI_COMPARISON_RESEARCH_DEMO` |
| comparison-research --output | `AGENTICAI_COMPARISON_RESEARCH_OUTPUT` |
| comparison-app.py --port | `AGENTICAI_COMPARISON_APP_PORT` |
| mem0-store --company | `AGENTICAI_MEM0_STORE_COMPANY` |
| rag-hybrid-query --source-name | `AGENTICAI_RAG_HYBRID_QUERY_SOURCE_NAME` |

The same keys work in the environment and the selected `.env`-format file. Existing
keys such as PINECONE_INDEX_NAME/PINECONE_INDEX, PINECONE_NAMESPACE,
OPENAI_EMBEDDING_MODEL/OPENAI_EMBEDDING_DIMENSIONS, OPENAI_CHAT_MODEL, QUESTION,
MEMORY_METHOD, OPENAI_MONTHLY_BILL_LIMIT_USD/OPENAI_MONTHLY_TOKEN_BUDGET and each
launcher's port/address keys remain supported. Within a single source, a canonical
key beats its legacy alias; a file alias still overrides an environment canonical
key because file values have higher precedence.

Credentials and settings without CLI flags, such as OPENAI_API_KEY and
TAVILY_API_KEY, remain environment/configuration-file variables. File values
override environment values. No secret values are logged by the parser.
The selected file is inherited by the Streamlit app; helpers do not reload a
different root `.env` over it. An explicitly selected missing/unreadable file is
a usage error. Help remains available without loading the selected file.

Booleans accept true/false, yes/no or 1/0. Repeatable options use a JSON array of
strings in configuration. Supplying that option on the CLI replaces the configured
list; repeated CLI occurrences then append to each other. Positionals can be
configured but an explicit positional wins. For example, `research.env`:

```dotenv
AGENTICAI_COMPARISON_RESEARCH_COMPANY=Toyota
AGENTICAI_COMPARISON_RESEARCH_DEMO=true
AGENTICAI_COMPARISON_RESEARCH_OUTPUT=demo.json
AGENTICAI_RAG_HYBRID_QUERY_SOURCE_NAME='["FAQs.md", "User Guides.md"]'
```

```bash
uv run python bin/agenticai-comparison-research --config research.env
uv run python bin/agenticai-comparison-research Honda --config research.env --output honda.json
```

Configuring the company also satisfies the required company input. Never commit
configuration files containing secrets. Do not copy live credentials into examples.

## Commands

| Command | Inputs and key options |
| --- | --- |
| `agenticai-comparison-research` | Required company positional; `--demo`, `--format json\|markdown`, `--output`, `--memory-method MEM0\|FILESYSTEM` |
| `agenticai-comparison-app.py` | Streamlit launcher: `--port`, `--address` |
| `agenticai-support-app.py` | Direct Python execution launches Streamlit; same `--port`, `--address`; execution inside Streamlit renders the UI |
| `agenticai-mem0-store` | JSON file positional (`-` for stdin), required `--company`, optional `--kind`, `--run-id` |
| `agenticai-mem0-query` | Optional `--company`, `--run-id`, `--kind`, pagination; `--memory-id` retrieves one record |
| `agenticai-openai-chat` | Optional question positional; prompts when omitted |
| `agenticai-openai-conversation` | Interactive terminal conversation |
| `agenticai-openai-admin` | `--list-models`, `--api-key-env`, usage window and monthly budget options |
| `agenticai-vectordb-upsert` | Input/index/namespace, embedding/chunk/batch options and `--dry-run` |
| `agenticai-vectordb-query` | Index/namespace, `--all-namespaces`, `--batch-size`, `--show-chunks` |
| `agenticai-rag-hybrid-query` | `--question`, index/namespace, model, retrieval and filter options; prompts if question is absent |
| `agenticai-generate-test-questions` | `--output` (default `20Questions.md` in current directory), `--count`, `--model`, `--context-budget`, `--seed` |

The `.sh` app wrappers forward all arguments to their matching Python entry point
and launch one server. Comparison listener defaults come from
`P3_STREAMLIT_PORT` (5555) and `P3_STREAMLIT_ADDRESS` (127.0.0.1). Support listener
defaults come from `STREAMLIT_SUPPORT_APP_PORT` (8501) and
`STREAMLIT_SUPPORT_APP_ADDRESS` (127.0.0.1).

## Examples

```bash
uv run python bin/agenticai-comparison-research --help
uv run python bin/agenticai-comparison-research Demo --demo --output demo.json
uv run python bin/agenticai-comparison-research Salesforce --memory-method MEM0 --format markdown --output salesforce.md
./bin/agenticai-comparison-app.sh --port 5556 --debug
./bin/agenticai-support-app.sh --port 8502
uv run python bin/agenticai-openai-chat "How do reminders work?" --debug
uv run python bin/agenticai-rag-hybrid-query --question "How do reminders work?"
```

Research output files are created exclusively; existing files are preserved. A
failed research run can leave an empty output file. Live comparison defaults to
`MEMORY_METHOD` from `.env`, falling back to `FILESYSTEM` for compatibility with
the previous script; `--memory-method` overrides it. Filesystem memory still has
its existing raw-company filename limitation. Use MEM0 for names containing URLs.
Demo mode runs fictional services and makes no external service calls.

`uv run python -m unittest discover -s tests -p test_cli.py -v` verifies help,
unknown options, explicit argv, validation, question handling, launcher forwarding
and offline research export. Tests do not require live provider credentials.
