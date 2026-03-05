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

      retriever = vectorstore.as_retriever(search_kwargs={"k": 8})
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
      "You have access to a tool that retrieves relevant pages that were previously crawled and embedded. Use the tool to find relevant information before answering questions. "
      "When the user asks what you can help with, or what you can do, or similar (e.g. 'what can you help me with', 'what can you do for me', 'what do you do', 'what do you offer'), you MUST: (1) Call the retrieval tool with a broad query (e.g. 'menu hours contact find us catering ordering app rewards') to get relevant page URLs. (2) Reply with a single intro line ending with a colon, then a bullet list. CRITICAL format for each line: the section name is PLAIN TEXT (no brackets, not a link). After the section text put a space and then exactly one markdown link whose visible text is only the word 'Open' or the arrow '→'. So each line must look like: - Our menu (drinks, pastries, sandwiches) [Open](URL). Do NOT write [Our menu (drinks, pastries, sandwiches)](URL) or any format where the section name is inside the link. The link must contain only 'Open' or '→' as the link text. Always include this full set (adapt the plain-text labels to the site): our menu (drinks, pastries, sandwiches, or similar); our hours; where to find us; how to reach us / contact; catering (menu, hosting events); ordering ahead / our app; rewards or loyalty. Use only URLs that appear in the retrieval tool output (copy the exact 'Source:' URL). Never guess or construct URLs (e.g. do not assume https://domain.com/catering exists). If the tool did not return a document with a URL for that section, list the section as plain text only with no [Open](URL)—e.g. '- Catering (menu, hosting events)' with no link—so the user does not get a 404. Only add [Open](URL) when that exact URL was in the tool results. Example:\n\n"
      "We can help you find what you need about [Business Name]:\n"
      "- Our menu (drinks, pastries, sandwiches) [Open](URL)\n"
      "- Operating hours [Open](URL)\n"
      "- Where to find us [Open](URL)\n"
      "- Contact us [Open](URL)\n"
      "- Catering (menu, hosting events) [Open](URL)\n"
      "- Order ahead / our app [Open](URL)\n"
      "- Rewards [Open](URL)\n\n"
      "Match section labels to the business. Only use a URL that appeared in the tool's Source: lines. If you have no URL for a section, omit the link (plain text only). Never guess URLs. Remember: section name = plain text; only [Open](URL) when that URL was in the tool output. "
      "When the user asks for an introduction or 'who are you' (without asking what you can do), respond with a short greeting only: e.g. 'Hello, this is [Business Name]. Ask us anything! We're here to help.' "
      "Only use a numbered-list format (1., 2., 3.) when the user explicitly asks for a list, "
      "e.g. 'in bullet points', 'in 3 points', 'numbered list', 'list the', 'summarize in X points'. "
      "Otherwise answer in normal paragraphs; do not include 'Source:' or raw source URLs in the response body (sources are shown separately in the UI). "
      "When you do use numbered points, format each point exactly like this. Use a blank line between each part so the title and description appear on their own lines. Do not add a 'Source:' line in the response; sources are displayed separately.\n"
      "1. **Bold title of the point**\n\n"
      "Description paragraph in normal text.\n\n"
      "Do not put a newline between the number and the bold title. Write exactly: number, space, then bold title on the same line (e.g. 2. **Title**). "
      "After the title, add a blank line, then the description. "
      "If you want to show a short identifier like a product code or object name inside a sentence, use inline code formatting (single backticks) so the sentence stays on one line. "
      "Only use fenced code blocks (triple backticks) as their own paragraph after you finish the sentence; never insert a fenced code block in the middle of a sentence. "
      "When your response is a substantive answer (not a greeting like 'Hello'), end the response with a new line and then exactly one line: TITLE: <2-5 word phrase summarizing the user's question>. "
      "Example: TITLE: Shipping Time Summary. Use title case. Do not add TITLE: for greetings or when the user has not asked a real question. "
      "If you cannot find the answer in the retrieved documentation, say so clearly."
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


def _fetch_page(url: str, timeout: float = 10.0) -> str:
  """Fetch raw HTML for a single URL."""
  headers = {
    "User-Agent": "CustomerServiceAgentBot/0.1 (+https://example.com)"
  }
  resp = requests.get(url, headers=headers, timeout=timeout)
  resp.raise_for_status()
  return resp.text


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


def ingest_urls(urls: List[str], max_depth: int = 1) -> Dict[str, Any]:
  """
  Crawl and embed the given URLs into the shared Chroma vector store.
  With max_depth=1, also fetches all same-site links from each seed URL (one level deep).
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
      html = _fetch_page(raw_url)
      text = _html_to_text(html)
      if text.strip():
        doc = Document(page_content=text, metadata={"source": raw_url})
        documents.append(doc)
      if max_depth >= 1:
        for link in _extract_same_site_links(html, raw_url, max_links=max_links_per_seed):
          if link not in seen:
            seen.add(link)
            depth_1_urls.append(link)
    except Exception as exc:  # noqa: BLE001
      errors.append({"url": raw_url, "error": str(exc)})

  # Depth 1: fetch same-site links discovered from seeds
  for raw_url in depth_1_urls:
    try:
      html = _fetch_page(raw_url)
      text = _html_to_text(html)
      if not text.strip():
        continue
      doc = Document(page_content=text, metadata={"source": raw_url})
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

  _, agent = _get_model_and_agent()

  messages = list(history or [])
  messages.append({"role": "user", "content": query})

  response = agent.invoke({"messages": messages})

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

