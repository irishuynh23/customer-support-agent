from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from core import ingest_urls, run_llm


class ChatMessage(BaseModel):
  role: str  # 'user' or 'assistant'
  content: str


class ChatRequest(BaseModel):
  prompt: str
  messages: Optional[List[ChatMessage]] = None
  business_id: Optional[str] = None


class ChatResponse(BaseModel):
  answer: str
  sources: List[str]


class IngestRequest(BaseModel):
  urls: List[HttpUrl]
  business_id: Optional[str] = None


class IngestResponse(BaseModel):
  indexed_pages: int
  errors: List[Dict[str, str]]


app = FastAPI(title="Customer Service Agent API", version="0.1.0")

origins = [
  "http://localhost:5173",
  "http://127.0.0.1:5173",
]

app.add_middleware(
  CORSMiddleware,
  allow_origins=origins,
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
  return {"status": "ok"}


@app.post("/api/ingest", response_model=IngestResponse)
def api_ingest(request: IngestRequest) -> IngestResponse:
  if not request.urls:
    raise HTTPException(status_code=400, detail="At least one URL is required.")

  result = ingest_urls([str(u) for u in request.urls], business_id=request.business_id)
  return IngestResponse(
    indexed_pages=int(result.get("indexed_pages", 0)),
    errors=result.get("errors", []),
  )


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
  prompt = (request.prompt or "").strip()
  if not prompt:
    raise HTTPException(status_code=400, detail="Prompt must not be empty.")

  history = (
    [{"role": m.role, "content": m.content} for m in (request.messages or [])]
    or None
  )

  try:
    result: Dict[str, Any] = run_llm(prompt, history=history, business_id=request.business_id)
  except Exception as exc:  # noqa: BLE001
    raise HTTPException(status_code=500, detail="Failed to process request.") from exc

  answer = str(result.get("answer", "")).strip() or "(No answer returned.)"

  # Build a de-duplicated list of sources from context docs
  context_docs = result.get("context") or []
  raw_sources = [
    str((getattr(doc, "metadata", None) or {}).get("source", "Unknown"))
    for doc in context_docs
  ]
  seen = set()
  sources: List[str] = []
  for src in raw_sources:
    if src not in seen:
      seen.add(src)
      sources.append(src)

  return ChatResponse(answer=answer, sources=sources)


if __name__ == "__main__":
  import uvicorn

  uvicorn.run(app, host="0.0.0.0", port=8000)

