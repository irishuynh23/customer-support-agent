---
name: dynamic-website-ingestion-customer-support-agent
overview: Extend the existing LangChain documentation helper into a generic customer-support style agent where a business can input one or more website URLs, we crawl and embed that content into a local vector store, and then answer user questions about those sites. Preserve the existing chat UI while adding a URL ingestion flow and optional link additions mid-conversation.
todos:
  - id: switch-to-chroma
    content: Refactor backend/core.py to use a shared local Chroma vector store instead of Pinecone, with a get_vectorstore() helper
    status: pending
  - id: add-url-ingestion-helper
    content: "Implement an ingest_urls(urls: list[str]) helper to crawl pages and add LangChain Documents into the shared vector store"
    status: pending
  - id: create-api-ingest-endpoint
    content: Add POST /api/ingest endpoint in api_server.py that accepts URLs, calls ingest_urls, and returns a status payload
    status: pending
  - id: frontend-url-panel
    content: Extend App.tsx with a URL input panel that calls /api/ingest, tracks indexing state, and shows readiness messages
    status: pending
  - id: preserve-clear-chat-behavior
    content: Ensure Clear chats only resets conversations while ingested knowledge in the vector store remains, and add optional UI hints about which sites are indexed
    status: pending
isProject: false
---

### High-level behavior

- **Goal**: Turn the current "LangChain docs helper" into a **generic customer-service helper** where a business can:
  - Provide one or more **website URLs** (e.g. their product catalog, FAQ, shipping policy pages).
  - The backend **crawls and embeds** those pages into a vector store.
  - Once ingestion finishes, the assistant can answer product and policy questions (shipping times, colors, pricing, etc.).
  - During a session, the business can **add more URLs** at any time; new content is appended to the same knowledge base.
  - **Clear chat** resets the conversation but **does not erase the ingested knowledge** (unless we add a separate "Clear knowledge" later).
- **Constraints / choices** (based on your comments):
  - Use a **free / local vector store** (e.g. Chroma) instead of paid Pinecone.
  - Avoid paid Tavily if possible; prefer a basic in-house crawler (requests + HTML parsing) that’s easy to swap later.
  - Keep multi-business support simple for now: assume **one business / knowledge base per backend run**, but design the code so adding a `project_id` / namespace later is straightforward.

---

### Backend changes

1. **Switch retrieval to a local vector store (Chroma) instead of Pinecone**
  - In `[backend/core.py](backend/core.py)`:
    - Replace `PineconeVectorStore` usage with `Chroma` (from `langchain_chroma`) backed by a local directory (e.g. `chroma_db/`), similar to what you previously did in `ingestion.py`.
    - Keep using `OpenAIEmbeddings` (or your chosen embedding model) but make the embeddings + Chroma index **module-level singletons** so ingestion and retrieval share them.
  - Result: all ingested documents are stored on disk (free, persistent across restarts) and `run_llm` will search that local Chroma store instead of Pinecone.
2. **Factor out a reusable `get_vectorstore()` helper**
  - In `[backend/core.py](backend/core.py)`:
    - Create something like `def get_vectorstore() -> Chroma:` that:
      - Lazily initializes embeddings.
      - Lazily creates/loads a Chroma collection under `chroma_db/`.
    - Replace `vectorstore = PineconeVectorStore(...)` in the `retrieve_context` tool with a call to `get_vectorstore()`.
  - This gives us a single, shared vector store for both ingestion and retrieval.
3. **Add an ingestion function to crawl + index URLs**
  - New helper in `[backend/core.py](backend/core.py)` or a small new module `backend/ingest_urls.py`:
    - `async def ingest_urls(urls: list[str]) -> dict:` (or sync if simpler).
    - For each URL:
      - Fetch HTML via `requests` (or `httpx`) with basic error handling and a user-agent.
      - Optionally follow same-domain links up to a small depth and page limit (e.g. depth 1, max 20 pages) to avoid huge crawls.
      - Parse content using `BeautifulSoup` / `trafilatura` to get clean text.
      - Create `Document` objects with `page_content` and `metadata` including `source` (URL).
    - Use `get_vectorstore()` to **add these documents** (e.g. `vectorstore.add_documents(documents)`).
    - Return a small status payload like `{ "indexed_pages": N, "errors": [...optional...] }`.
  - This replaces the Tavily-specific ingestion so you don’t need a Tavily key.
4. **New API endpoint for ingestion**
  - In `[api_server.py](api_server.py)`:
    - Define a `Pydantic` model, e.g. `class IngestRequest(BaseModel): urls: List[str]`.
    - Add a route: `POST /api/ingest` that:
      - Validates there is at least one URL; optionally ensure they start with `http://` or `https://` and are within some length.
      - Calls `ingest_urls(request.urls)`.
      - Returns a JSON response with status, e.g. `{ "status": "ready", "indexed_pages": N }`.
    - For MVP keep it **synchronous** (the request waits until indexing is done); later we could turn it into a background job with progress tracking.
5. **Ensure `run_llm` always uses the latest ingested docs**
  - Because `get_vectorstore()` and `ingest_urls()` share the same Chroma instance, no extra work is needed: any new documents are visible to the retrieval tool immediately.
  - Keep the existing behavior where, if the answer cannot be found in the docs, the assistant says so (as already described in the `system_prompt`).

---

### Frontend changes

1. **Add a URL input flow before questions**
  - In `[frontend/src/App.tsx](frontend/src/App.tsx)`:
    - Add state for website URLs and ingestion status, e.g. `const [sourceUrls, setSourceUrls] = useState<string[]>([])`, `const [isIndexing, setIsIndexing] = useState(false)`, `const [indexStatus, setIndexStatus] = useState<string | null>(null)`.
    - Add a small panel above the chat messages (or in the sidebar) with:
      - A text input for a URL.
      - An **“Add site”** button.
      - A list of added URLs (read‑only) so the business sees what has been ingested.
    - When the user clicks **Add site**:
      - Call `POST /api/ingest` with `{ urls: [url] }`.
      - Show a status state: e.g. `"Indexing…"`, disable the button, and optionally disable sending questions while `isIndexing` is true.
      - On success, update `sourceUrls` and show `"Indexed N pages – I’m ready to answer questions."`.
      - On failure, show a small error banner.
2. **Allow adding more links mid‑conversation**
  - Keep the **URL panel always visible** so the business can add new URLs at any time.
  - Each **additional ingest call** simply appends new pages to the same vector store; no need to reset chat.
  - Do **not** touch the existing `Clear chats` logic – it should still reset only the conversation history, not the vector store content.
3. **Minor UI feedback for readiness**
  - When no URLs have been ingested yet, display a subtle banner in the messages area or under the URL panel, e.g.: `"Add at least one site above so I can answer questions about your content."`
  - Once `sourceUrls.length > 0`, change the banner to something like `"Using N site(s) as knowledge."` (optional; complements the header pills you already added).

---

### Data & session behavior

1. **Separation of chat vs. knowledge**
  - **Clear chats**:
    - Keeps the vector store (knowledge) intact but wipes the conversations in `localStorage` and resets to a fresh conversation.
  - **App restart**:
    - Because Chroma persists to disk, previously ingested docs remain available unless you delete the `chroma_db/` directory.
2. **Future‑proofing for multiple businesses (optional, later)**
  - When you want multi‑tenant support, introduce a `project_id` / `workspace_id` concept:
    - Add it to `IngestRequest` and chat requests.
    - Use it as a **namespace** or separate Chroma collection so each business has its own vector space.
  - The ingestion and retrieval signatures will already be structured enough to accept this extra parameter later.

---

### Latency & cost notes

- **Latency**:
  - Ingestion latency is dominated by **network fetch** + **embedding calls**, not by whether the vector store is persistent or per‑runtime.
  - Using a local Chroma store avoids remote vector DB latency and is free once embeddings are computed.
- **Costs**:
  - No Pinecone or Tavily subscription is required.
  - Only remaining cost is your **LLM + embeddings provider** (e.g. OpenAI) per token; you can control this by limiting page count and text length per crawl.

This plan keeps your current UI almost unchanged, adds a clean URL ingestion flow, switches you to a local free vector store, and keeps the design ready to grow into a true multi‑tenant product later.