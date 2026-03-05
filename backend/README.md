# Customer Service Agent – Backend

FastAPI backend: ingest website URLs (crawl + embed into Chroma), then answer questions via chat.

## Setup

1. **Create virtualenv and install dependencies**

   From this directory (`customer-service-agent/backend/`):

   ```bash
   pipenv install
   ```

   If Pipenv has permission issues, use a venv instead:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # or: .venv\Scripts\activate on Windows
   pip install fastapi uvicorn python-dotenv requests beautifulsoup4 langchain langchain-openai langchain-chroma langchain-text-splitters langchain-core
   ```

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

Indexed data is stored in `chroma_db/` (created in the current working directory when you first ingest).
