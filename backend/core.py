import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain.messages import ToolMessage
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.tools import tool

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse


load_dotenv()

_embeddings: Optional[OpenAIEmbeddings] = None
_vectorstore: Optional[Chroma] = None
_model = None
_agent = None
_current_business_id: Optional[str] = None


def _get_embeddings_and_vectorstore() -> Tuple[OpenAIEmbeddings, Chroma]:
  """Lazily initialize and return embeddings and local Chroma vector store."""
  global _embeddings, _vectorstore  # noqa: PLW0603

  if _embeddings is None:
    _embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

  if _vectorstore is None:
    _vectorstore = Chroma(
      persist_directory="chroma_db",
      embedding_function=_embeddings,
    )

  return _embeddings, _vectorstore


def _get_model_and_agent():
  """Lazily initialize and return the chat model and agent."""
  global _model, _agent  # noqa: PLW0603

  if _model is None:
    _model = init_chat_model("gpt-5.2", model_provider="openai")

  if _agent is None:
    _, vectorstore = _get_embeddings_and_vectorstore()

    @tool(response_format="content_and_artifact")
    def retrieve_context(query: str):  # type: ignore[unused-ignore]
      """Retrieve relevant documentation to help answer user queries about the indexed sites."""

      global _current_business_id  # noqa: PLW0603

      search_kwargs: Dict[str, Any] = {"k": 8}
      if _current_business_id:
        search_kwargs["filter"] = {"business_id": _current_business_id}

      retriever = vectorstore.as_retriever(search_kwargs=search_kwargs)
      retrieved_docs = retriever.invoke(query)

      serialized = "\n\n".join(
        (
          f"Source: {doc.metadata.get('source', 'Unknown')}\n\nContent: {doc.page_content}"
        )
        for doc in retrieved_docs
      )

      return serialized, retrieved_docs

    system_prompt = (
      "You represent the business whose website content was indexed. Speak as the business: use we, our, and us (e.g. 'We offer...', 'Our hours are...', 'Contact us at...'). Do not use I, my, or me. "
      "CRITICAL: Your only source of information is the content returned by the retrieval tool. Do not use general knowledge, assumptions, or anything outside the retrieved documentation. If the answer is not in the retrieved content, say so clearly (e.g. 'I couldn't find that information on the site' or 'That isn\'t covered in the pages we have') and do not invent an answer. "
      "You have access to a tool that retrieves relevant pages that were previously crawled and embedded. Always use the tool to find relevant information before answering; base your answer only on what the tool returns. "
      "When the user asks what you can help with, or what you can do, or similar (e.g. 'what can you help me with', 'what can you do for me', 'what do you do', 'what do you offer'), you MUST: (1) Call the retrieval tool with a broad query (e.g. 'menu hours contact find us catering reservations') to get relevant page URLs. (2) Reply with a single intro line ending with a colon, then a bullet list. CRITICAL: List ONLY sections that are actually present in the retrieved documents—i.e. only include a line if the tool returned at least one document whose content or Source URL clearly corresponds to that topic. Do NOT list generic categories (e.g. 'ordering ahead / our app', 'rewards or loyalty') unless the retrieved content actually has a page or link about that. If the site has no app, no ordering ahead, and no rewards/loyalty program, do not mention them. Build the list from what the tool returned; do not use a fixed template. Format for each line: section name as PLAIN TEXT, then a space, then exactly one markdown link with visible text 'Open' or '→' only when you have a URL from the tool's Source lines for that section—e.g. '- Our menu [Open](URL)'. If you have no URL for a topic, do not include that topic in the list at all (do not list it as plain text without a link). Use only URLs that appear in the retrieval tool output. Never guess or construct URLs. Example (only if those sections exist in the retrieved docs):\n\n"
      "We can help you find what you need about [Business Name]:\n"
      "- Our menu [Open](URL)\n"
      "- Hours [Open](URL)\n"
      "- Find us / Contact [Open](URL)\n"
      "- Catering / private dining [Open](URL)\n\n"
      "Match section labels to the business. Only list sections that have a corresponding document/URL in the tool output; only use URLs from the tool's Source lines; never add sections the site does not have. "
      "When the user asks for an introduction or 'who are you' (without asking what you can do), respond with a short greeting only: e.g. 'Hello, this is [Business Name]. Ask us anything! We're here to help.' "
      "Only use a numbered-list format (1., 2., 3.) when the user explicitly asks for a list, "
      "e.g. 'in bullet points', 'in 3 points', 'numbered list', 'list the', 'summarize in X points'. "
      "Otherwise answer in normal paragraphs; do not include 'Source:' or raw source URLs in the response body (sources are shown separately in the UI). "
      "Reservation and contact links: When the user asks how to reserve or book, lead with one direct clickable link so they can go straight there. If the retrieved docs contain a reservation/reserve page URL (e.g. /reserve, /book), use it: e.g. 'You can [make a reservation here](URL).' If there is no dedicated reserve URL in the docs but you have the main site or homepage URL, use that: e.g. 'You can reserve through our website: [Site name or Visit us](homepage URL).' Do not only give step-by-step instructions without a link—always include one clickable link (reserve page, third-party booking site like OpenTable, or front page) first; the URL in Source may be the direct booking link—use it so the user goes straight there. You may add a short line after (e.g. 'then choose Above Ground or Below Ground') if needed. Use only URLs from the tool's Source lines. When you give a contact email from the retrieved content, format it as a clickable mailto link: [email@example.com](mailto:email@example.com). Use only emails and URLs from the retrieval output. "
      "When you do use numbered points, format each point exactly like this. Use a blank line between each part so the title and description appear on their own lines. Do not add a 'Source:' line in the response; sources are displayed separately.\n"
      "1. **Bold title of the point**\n\n"
      "Description paragraph in normal text.\n\n"
      "Do not put a newline between the number and the bold title. Write exactly: number, space, then bold title on the same line (e.g. 2. **Title**). "
      "After the title, add a blank line, then the description. "
      "If you want to show a short identifier like a product code or object name inside a sentence, use inline code formatting (single backticks) so the sentence stays on one line. "
      "Only use fenced code blocks (triple backticks) as their own paragraph after you finish the sentence; never insert a fenced code block in the middle of a sentence. "
      "When your response is a substantive answer (not a greeting like 'Hello'), end the response with a new line and then exactly one line: TITLE: <2-5 word phrase summarizing the user's question>. "
      "Example: TITLE: Shipping Time Summary. Use title case. Do not add TITLE: for greetings or when the user has not asked a real question. "
      "If you cannot find the answer in the retrieved documentation, say so clearly. Do not guess or make up information; only state what is present in the retrieved content."
    )

    _agent = create_agent(_model, tools=[retrieve_context], system_prompt=system_prompt)

  return _model, _agent


def _clean_url(url: str) -> str:
  url = url.strip()
  if not url:
    return url
  if not url.startswith(("http://", "https://")):
    url = "https://" + url
  return url


def _fetch_page(url: str, timeout: float = 10.0) -> Tuple[str, str]:
  """Fetch raw HTML for a single URL. Returns (html_text, final_url). Uses final URL after redirects so third-party reservation links (e.g. OpenTable) are stored directly."""
  headers = {
    "User-Agent": "CustomerServiceAgentBot/0.1 (+https://example.com)"
  }
  resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
  resp.raise_for_status()
  final_url = resp.url or url
  return resp.text, final_url


def _html_to_text(html: str) -> str:
  """Very simple HTML -> visible text extraction."""
  soup = BeautifulSoup(html, "html.parser")

  # Remove script/style elements
  for tag in soup(["script", "style", "noscript"]):
    tag.extract()

  text = soup.get_text(separator="\n")
  # Normalize whitespace a bit
  lines = [line.strip() for line in text.splitlines()]
  chunks = [line for line in lines if line]
  return "\n".join(chunks)


def _extract_same_site_links(html: str, base_url: str, max_links: int = 100) -> List[str]:
  """Extract same-site (same netloc) HTTP/HTTPS links from HTML. Returns deduped list."""
  soup = BeautifulSoup(html, "html.parser")
  base_parsed = urlparse(base_url)
  base_netloc = base_parsed.netloc
  seen: set[str] = set()
  out: List[str] = []
  for a in soup.find_all("a", href=True):
    if len(out) >= max_links:
      break
    href = (a["href"] or "").strip()
    if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
      continue
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
      continue
    if parsed.netloc != base_netloc:
      continue
    without_fragment = urlunparse(parsed._replace(fragment=""))
    if without_fragment not in seen:
      seen.add(without_fragment)
      out.append(without_fragment)
  return out


def ingest_urls(
  urls: List[str],
  max_depth: int = 2,
  business_id: Optional[str] = None,
) -> Dict[str, Any]:
  """
  Crawl and embed the given URLs into the shared Chroma vector store.
  With max_depth=1, fetches same-site links from each seed (one level). With max_depth=2, also fetches links from those pages (two levels).
  """
  _, vectorstore = _get_embeddings_and_vectorstore()

  cleaned_seeds = [_clean_url(u) for u in urls if _clean_url(u)]
  seen: set[str] = set()
  documents: List[Document] = []
  errors: List[Dict[str, str]] = []
  max_links_per_seed = 50

  # Depth 0: fetch seed URLs
  depth_1_urls: List[str] = []
  for raw_url in cleaned_seeds:
    if raw_url in seen:
      continue
    seen.add(raw_url)
    try:
      html, final_url = _fetch_page(raw_url)
      text = _html_to_text(html)
      if text.strip():
        metadata: Dict[str, Any] = {"source": final_url}
        if business_id:
          metadata["business_id"] = business_id
        doc = Document(page_content=text, metadata=metadata)
        documents.append(doc)
      if max_depth >= 1:
        for link in _extract_same_site_links(html, raw_url, max_links=max_links_per_seed):
          if link not in seen:
            seen.add(link)
            depth_1_urls.append(link)
    except Exception as exc:  # noqa: BLE001
      errors.append({"url": raw_url, "error": str(exc)})

  # Depth 1: fetch same-site links discovered from seeds
  depth_2_urls: List[str] = []
  for raw_url in depth_1_urls:
    try:
      html, final_url = _fetch_page(raw_url)
      text = _html_to_text(html)
      if not text.strip():
        continue
      metadata = {"source": final_url}
      if business_id:
        metadata["business_id"] = business_id
      doc = Document(page_content=text, metadata=metadata)
      documents.append(doc)
      if max_depth >= 2:
        for link in _extract_same_site_links(html, raw_url, max_links=max_links_per_seed):
          if link not in seen:
            seen.add(link)
            depth_2_urls.append(link)
    except Exception as exc:  # noqa: BLE001
      errors.append({"url": raw_url, "error": str(exc)})

  # Depth 2: fetch same-site links discovered from depth 1
  for raw_url in depth_2_urls:
    try:
      html, final_url = _fetch_page(raw_url)
      text = _html_to_text(html)
      if not text.strip():
        continue
      metadata = {"source": final_url}
      if business_id:
        metadata["business_id"] = business_id
      doc = Document(page_content=text, metadata=metadata)
      documents.append(doc)
    except Exception as exc:  # noqa: BLE001
      errors.append({"url": raw_url, "error": str(exc)})

  if not documents:
    return {"indexed_pages": 0, "errors": errors}

  splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=200,
    separators=["\n\n", "\n", " ", ""],
  )
  chunks = splitter.split_documents(documents)

  vectorstore.add_documents(chunks)

  return {"indexed_pages": len(chunks), "errors": errors}


def run_llm(
  query: str,
  history: Optional[List[Dict[str, str]]] = None,
  business_id: Optional[str] = None,
) -> Dict[str, Any]:
  """
  Run the RAG pipeline to answer a query using retrieved website content.

  Args:
      query: The user's question

  Returns:
      Dictionary containing:
          - answer: The generated answer
          - context: List of retrieved documents
  """

  global _current_business_id  # noqa: PLW0603

  _, agent = _get_model_and_agent()

  messages = list(history or [])
  messages.append({"role": "user", "content": query})

  _current_business_id = business_id
  try:
    response = agent.invoke({"messages": messages})
  finally:
    _current_business_id = None

  # Extract the answer from the last AI message
  answer = response["messages"][-1].content

  # Extract context documents from ToolMessage artifacts
  context_docs: List[Document] = []
  for message in response["messages"]:
    if isinstance(message, ToolMessage) and hasattr(message, "artifact"):
      if isinstance(message.artifact, list):
        context_docs.extend(message.artifact)

  return {
    "answer": answer,
    "context": context_docs,
  }


if __name__ == "__main__":
  result = run_llm(query="What can you tell me about shipping?")
  print(result)

