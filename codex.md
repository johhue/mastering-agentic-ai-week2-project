# Codex Build Log

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

We created `upsert_to_pinecone.py`.

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

We created `query_pinecone.py`.

This script connects to Pinecone and lists the source files represented by upserted vectors.

Run it with:

```bash
uv run python query_pinecone.py
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
uv run python query_pinecone.py --show-chunks
```

## Streamlit Chatbot

We created `support_chatbot.py`.

This is the main customer support chatbot UI. It uses Streamlit and supports hybrid retrieval:

- Local keyword search over the RemindMe files
- Semantic search through Pinecone
- Weighted hybrid score merging
- OpenAI answer generation over retrieved context
- Source display with retrieval confidence
- Confidence-based escalation to a human

The chatbot avoids guessing by default. If retrieval confidence is too low, it routes the question to a human support specialist instead of inventing an answer.

## Streamlit Launcher

We created `run_support_chatbot.sh`.

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

We created `query_openai_pinecone.py`.

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

We created `generate_test_questions.py`.

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
- `support_chatbot.py` loaded the local corpus
- `query_pinecone.py` found `92` vectors and `11` files in Pinecone
- `query_openai_pinecone.py` successfully answered a live RAG question
- `generate_test_questions.py` created `20Questions.md`

## Final Workflow

1. Put secrets in `.env`.
2. Upload RemindMe data to Pinecone:

   ```bash
   uv run python upsert_to_pinecone.py
   ```

3. Confirm uploaded files:

   ```bash
   uv run python query_pinecone.py
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

