# Customer Service Agent – Backend

FastAPI backend: ingest website URLs (crawl + embed into Chroma), then answer questions via chat.

## Python version

Use **Python 3.11 or 3.12**. Python 3.14 is not supported (ChromaDB/Pydantic compatibility). If you see `ConfigError: unable to infer type for attribute "chroma_server_nofile"`, you're on 3.14—recreate the env with 3.11 or 3.12.

## Setup

1. **Create virtualenv and install dependencies**

   From this directory (`customer-service-agent/backend/`):

   If you have Python 3.11 or 3.12 installed:

   ```bash
   pipenv --rm
   pipenv install --python 3.11
   ```

   Or with a specific path: `pipenv install --python /opt/homebrew/bin/python3.11` (adjust path for your system). On macOS with Homebrew: `brew install python@3.11` then `pipenv install --python $(brew --prefix python@3.11)/bin/python3.11`.

   If Pipenv has permission issues, use a venv instead:

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate   # or: .venv\Scripts\activate on Windows
   pip install fastapi uvicorn python-dotenv requests beautifulsoup4 langchain langchain-openai langchain-chroma langchain-text-splitters langchain-core
   ```
   Use `python3.11` (or `python3.12`) so the venv is not Python 3.14.

2. **Environment variables**

   Create a `.env` file here (or export in the shell). You need:

   - `OPENAI_API_KEY` – used for embeddings and the chat model.

   Example:

   ```
   OPENAI_API_KEY=sk-...
   ```

3. **Run the API server**

   From `customer-service-agent/backend/`:

   ```bash
   pipenv run uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
   ```

   Or with venv:

   ```bash
   uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
   ```

   Server will be at `http://localhost:8000`. Docs: `http://localhost:8000/docs`.

## API

- **GET /health** – health check.
- **POST /api/ingest** – body: `{ "urls": ["https://example.com", ...] }`. Crawls and indexes those URLs into the local Chroma store. Returns `{ "indexed_pages": N, "errors": [] }`.
- **POST /api/chat** – body: `{ "prompt": "Your question", "messages": [] }`. Returns `{ "answer": "...", "sources": ["url1", ...] }`.

## Crawling behavior

- **Same-site link depth:** The crawler follows same-site links up to **2 levels deep by default** (seed → depth 1 → depth 2).
- **Redirects:** HTTP redirects are followed, and the **final URL after redirects** is stored as the document `source`. This helps the assistant return direct third-party booking links (e.g. OpenTable/Resy) when a restaurant’s “Reserve” page redirects externally.

Indexed data is stored in `chroma_db/` (created in the current working directory when you first ingest).
