---
name: customer-service-agent-blueprint
overview: Design a new customer-service agent app in customer-service-agent/ that lets a business input website URLs, crawls and embeds them into a local vector store, and then answers customer questions via a ChatGPT-style React frontend similar to the existing LangChain helper.
todos:
  - id: backend-scaffold
    content: Create backend FastAPI scaffold in customer-service-agent/backend with core.py and api_server.py using a shared local Chroma vector store
    status: pending
  - id: implement-url-ingestion
    content: Implement ingest_urls to crawl/parse URLs and add documents into the Chroma vector store
    status: pending
  - id: wire-chat-endpoint
    content: Wire run_llm and retrieval logic into a POST /api/chat endpoint that mirrors the LangChain helper behavior
    status: pending
  - id: frontend-scaffold
    content: Copy and adapt the existing my-doc-assistant React app into customer-service-agent/frontend with a URL ingestion panel
    status: pending
  - id: session-behavior
    content: Ensure clear chats resets only conversations while ingested site content remains, and allow users to add more links mid-session
    status: pending
isProject: false
---

### Customer Service Agent – High-Level Blueprint

#### 1. Project structure

- `[customer-service-agent/]`
  - `[backend/]`
    - `core.py` – shared embeddings + vector store, retrieval + LLM logic, URL ingestion helpers.
    - `api_server.py` – FastAPI app with `/health`, `/api/ingest`, `/api/chat`.
    - `Pipfile` / `requirements.txt` – backend deps (FastAPI, uvicorn, langchain, langchain-openai, langchain-chroma, httpx/requests, beautifulsoup4 or trafilatura, python-dotenv).
  - `[frontend/]`
    - React + Vite + TypeScript scaffold, mirroring layout and styling from `my-doc-assistant/frontend/`.
    - `src/App.tsx` – main UI: URL ingestion panel + chat interface.
    - `src/App.css` / `src/index.css` – copy + adapt styles for colors, scrollbars, layout.
  - `README.md` – product-focused readme for the customer-service agent.

---

#### 2. Backend architecture

```mermaid
flowchart TD
  user[BusinessUser] -->|POST /api/ingest (URLs)| apiIngest[FastAPI /api/ingest]
  apiIngest --> ingestUrls[ingest_urls helper]
  ingestUrls --> crawler[HTML fetch + parse]
  crawler --> chunker[text splitter]
  chunker --> vectorstoreAdd[Chroma.add_documents]

  customer[EndCustomer] -->|POST /api/chat (question)| apiChat[FastAPI /api/chat]
  apiChat --> runLLM[run_llm]
  runLLM --> retriever[Chroma.as_retriever]
  retriever --> llm[Chat model]
  llm --> apiChat
  apiChat --> customer
```



- **Shared components in `[backend/core.py]`:**
  - `get_embeddings()` – lazily create `OpenAIEmbeddings`.
  - `get_vectorstore()` – lazily create/load a Chroma store (e.g. `chroma_db/`) using those embeddings.
  - `ingest_urls(urls: list[str])` – fetch + parse pages, chunk into `Document`s, add to vector store, return counts/errors.
  - `_get_model_and_agent()` + `run_llm()` – similar to your existing LangChain helper: use a retrieval tool over the shared vector store and a chat model (e.g. `gpt-4`/`gpt-5.x`).
- **FastAPI app in `[backend/api_server.py]`:**
  - `GET /health` – simple status.
  - `POST /api/ingest` – accepts `{ urls: string[] }`, calls `ingest_urls`, returns `{ status, indexed_pages, errors? }`.
  - `POST /api/chat` – accepts `{ prompt, messages? }`, calls `run_llm`, returns `{ answer, sources, suggested_title? }`.
- **Persistence behavior:**
  - Chroma persists to disk in `chroma_db/`, so ingested knowledge survives backend restarts.
  - Conversations can be stored in frontend state or `localStorage` (frontend concern), independent of the vector store.

---

#### 3. URL ingestion flow

- **Input:** list of website URLs from the business user.
- **Steps (inside `ingest_urls`):**
  1. Normalize and validate URLs (ensure `http/https`, cap length, avoid obviously bad input).
  2. For each URL:
    - Fetch HTML via `httpx`/`requests` with timeouts and a friendly user-agent.
    - Restrict crawling to same-domain links; optional depth 1 and max pages per root URL.
    - Extract readable text using `BeautifulSoup` or `trafilatura`.
    - Create `Document` objects with `page_content` and `metadata` (at least `source` URL, maybe title).
  3. Chunk documents with `RecursiveCharacterTextSplitter`.
  4. Call `get_vectorstore().add_documents(chunks)`.
  5. Return a summary: number of pages/docs indexed, and list of any URLs that failed.
- **Later extension:** add a `project_id` / `business_id` to scope content into separate collections or namespaces if you want true multi-tenant behavior.

---

#### 4. Chat + retrieval behavior

- **run_llm** in `[backend/core.py]`:
  - Builds `messages` from conversation history + the new user question.
  - Uses `create_agent` with a `retrieve_context` tool that:
    - Calls `get_vectorstore().as_retriever()` with a reasonable `k`.
    - Serializes retrieved docs with `Source: ...` and content for the LLM.
  - System prompt enforces:
    - Use docs to answer; if answer isn’t in docs, say you don’t know.
    - For numbered lists: `1. **Title`**, description, `Source: ...` (matches your existing formatting).
    - When referencing short identifiers (product names, attributes), prefer inline code ticks instead of mid-sentence fenced blocks.
  - Returns `{ answer, context_docs }` to `api_server`, which then formats `sources` from `context_docs`.

---

#### 5. Frontend layout and behavior

- Base on `my-doc-assistant/frontend` but under `[customer-service-agent/frontend/]`:
  - **Sidebar:**
    - New chat list, delete, clear chats (same as before).
    - Optional small note like `Customer Service Agent · Demo`.
  - **Header:**
    - App title (e.g. `Customer Service Agent`).
    - Docs/URLs summary pill: `Using: N site(s)`.
    - Optional model pill: `Model: gpt-4`.
  - **URL ingestion panel:**
    - Above the messages or in header/sidebar:
      - URL input box.
      - `Add site` button.
      - List of added sites.
      - Status text: `Indexing…`, `Indexed N pages – ready for questions.`
  - **Chat window:**
    - Same bubble style, streaming effect, markdown + code highlighting, scrollbars, retry button.
    - If no sites ingested yet, show a subtle banner prompting the user to add a site first.
- **State transitions:**
  - On `Add site`:
    - Call `POST /api/ingest`.
    - Show indexing state; optionally prevent sending questions until first ingest completes.
  - On success: append to `sourceUrls` state, show “ready” message.
  - Chat thereafter behaves like your LangChain helper.

---

#### 6. Clear chats and adding more links

- **Clear chats:**
  - Resets only the conversation list (state and localStorage), not the vector store.
  - A fresh welcome message appears, but previously ingested sites remain available.
- **Adding more links mid-chat:**
  - User can submit new URLs at any time.
  - Frontend calls `/api/ingest` again; new docs go into the same Chroma store.
  - No need to restart or clear chats; subsequent answers naturally incorporate the expanded knowledge base.

---

#### 7. Minimal MVP vs future enhancements

- **MVP (initial build):**
  - Single shared vector store for all content.
  - Simple crawler (shallow depth, capped pages).
  - Synchronous ingestion and Q&A.
- **Future enhancements:**
  - Multi-tenant: per-business collections or namespaces.
  - Background ingestion jobs with progress polling.
  - Admin UI to view or delete indexed pages.
  - Support for non-HTML sources (PDFs, CSVs, uploaded docs).

This blueprint keeps your successful LangChain-helper UX while generalizing the backend to handle arbitrary websites and focusing on free/local components for your personal project.