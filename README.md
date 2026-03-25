# Customer Support Agent

A customer support agent for businesses: answer common customer questions with responses grounded in the business’s website—hours, services, policies, and more—without guessing beyond what was actually crawled.

## Features

- **URL ingestion:** Paste URLs → backend crawls and embeds (same-site links, two levels deep by default). Status and errors shown in the sidebar.
- **Session persistence:** Ingested knowledge and session survive page refresh; only **End Session** clears them and asks for new URLs.
- **Business voice:** Agent answers as the business (we/our/us). “What can you do?” returns a short intro plus a list of sections with **Open** pills that link only to URLs that were actually retrieved (no guessed links, no 404s).
- **Chat:** Markdown, code blocks with syntax highlighting and copy, sources in a single **Sources** dropdown per message. Retry and clear chats.
- **End Session:** Clears session and conversations so you can enter new links and start fresh.

## Demo

![Customer Support Agent demo](./assets/customer_service_agent.gif)

## Architecture

Two pipelines share the same **Chroma** vector store. **`business_id`** (from the session) tags ingested chunks and **filters retrieval** so answers only use the current site’s documents.

```mermaid
flowchart TB
  subgraph ingest["Ingest — Load website(s)"]
    direction LR
    U1[User URLs] --> FE1[React]
    FE1 -->|POST /api/ingest| API1[FastAPI]
    API1 --> Crawl["Crawl same-site links (depth 2)"]
    Crawl --> Text["HTML to text"]
    Text --> Split["Chunk + OpenAI embeddings"]
    Split --> VS[(Chroma)]
  end

  subgraph chat["Chat — each message"]
    direction LR
    U2[User question] --> FE2[React]
    FE2 -->|POST /api/chat| API2[FastAPI]
    API2 --> Agent["LangChain agent + chat model"]
    Agent --> Tool["retrieve_context tool (k=8)"]
    Tool --> VS
    Tool --> Agent
    Agent --> Out["Answer + sources"]
  end
```

- **Ingest** does not run inside the agent; it runs once per “Load website(s)” to populate Chroma.
- **Chat** runs the agent: the model may call **`retrieve_context`** to pull relevant chunks before replying; the API surfaces **sources** from the tool’s retrieved documents.

## Tech stack

- **Backend:** FastAPI, LangChain, OpenAI (embeddings + chat), Chroma (local vector store), BeautifulSoup (HTML parsing)
- **Frontend:** React, TypeScript, Vite, react-markdown, react-syntax-highlighter
- **Crawling:** Same-site link following with configurable depth (default: 2 levels from each seed URL). Redirects are followed and the **final URL after redirects** is stored as the page source (useful for third-party booking links like OpenTable/Resy).

## Quick start

### 1. Backend

```bash
cd customer-service-agent/backend
pipenv install
```

Python version: use **Python 3.11 or 3.12** (Python 3.14 is not supported by current ChromaDB/Pydantic dependencies). If needed:

```bash
pipenv --rm
pipenv install --python 3.11
```

Create a `.env` file in `backend/` with:

```
OPENAI_API_KEY=sk-your-key
```

Run the API:

```bash
pipenv run uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
```

API base: `http://localhost:8000`. Docs: `http://localhost:8000/docs`.

See [backend/README.md](backend/README.md) for venv alternative and API details.

### 2. Frontend

In a separate terminal:

```bash
cd customer-service-agent/frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

### 3. Use the app

1. Paste one or more website URLs in the sidebar (e.g. `https://yoursite.com`).
2. Click **Load website(s)** and wait until you see “Done. Crawling and embedding finished…”
3. Ask questions in the chat (e.g. “What can you help me with?”, “What are your hours?”).
4. Use **End Session** when you want to start over and add a different site; use **Clear chats** to reset conversations but keep the current site’s knowledge.

## API endpoints

- **GET `/health`**: health check (returns `{ "status": "ok" }`).
- **POST `/api/ingest`**: crawl + embed URLs.
- **POST `/api/chat`**: ask questions, returns `answer` + `sources`.

## Project structure

```
customer-service-agent/
├── backend/          # FastAPI, ingest + chat API, Chroma, crawler
│   ├── core.py       # Embeddings, vector store, agent, ingest_urls, run_llm
│   ├── api_server.py # /health, /api/ingest, /api/chat
│   └── README.md     # Backend setup and API reference
├── frontend/         # React + Vite app
│   └── src/          # App, chat UI, URL panel, styles
├── chroma_db/        # Created at runtime (backend cwd) for vector store
└── README.md         # This file
```

## Environment

- **Backend:** `OPENAI_API_KEY` in `backend/.env` (see [backend/README.md](backend/README.md)).
- **Frontend:** Expects API at `http://localhost:8000` (see `API_BASE_URL` in `frontend/src/App.tsx` if you change the port).

## Troubleshooting

- **Seeing `GET / 404 Not Found` in backend logs**
  - This is expected. The backend is an API; `/` and `/favicon.ico` are not implemented. Use `http://localhost:8000/docs` or `GET /health` to verify it’s up.

