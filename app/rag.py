import ipaddress
import os
import socket
import time
import uuid
from collections.abc import Iterator
from functools import lru_cache
from urllib.parse import urlparse

os.environ.setdefault("USER_AGENT", "rag-document-assistant/1.0")

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader, WebBaseLoader
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings

settings = get_settings()

PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a document assistant. Answer the question using ONLY the context below. "
        "Cite the sources you use inline as [1], [2], etc. matching the context numbers. "
        "If the answer is not in the context, say you could not find it in the documents. "
        "Do not use outside knowledge.\n\nContext:\n{context}",
    ),
    ("human", "{question}"),
])


@lru_cache
def get_embeddings() -> FastEmbedEmbeddings:
    # ONNX runtime instead of PyTorch: same model and vectors, about half the memory (fits 512 MB free hosting).
    # Small batches matter most: the default of 256 peaks near 2 GB on a long PDF, batch 4 stays ~330 MB.
    return FastEmbedEmbeddings(
        model_name=settings.embed_model,
        cache_dir=settings.embed_cache_dir,
        batch_size=settings.embed_batch_size,
        threads=1,
    )


@lru_cache
def get_store() -> Chroma:
    return Chroma(
        collection_name="documents",
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_dir,
        # Cosine distance keeps relevance scores in 0..1 (the default L2 does not)
        collection_metadata={"hnsw:space": "cosine"},
    )


def get_llm() -> Runnable:
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0.2)

    from langchain_google_genai import ChatGoogleGenerativeAI

    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set. Add it to .env or switch LLM_PROVIDER to ollama.")

    def gemini(model: str) -> ChatGoogleGenerativeAI:
        # Fail fast on free-tier 503s instead of retrying for minutes
        return ChatGoogleGenerativeAI(
            model=model, google_api_key=settings.google_api_key, temperature=0.2, max_retries=1, timeout=60
        )

    llm = gemini(settings.gemini_model)
    if settings.gemini_fallback_model:
        llm = llm.with_fallbacks([gemini(settings.gemini_fallback_model)])
    return llm


# ---------- Ingestion ----------

def load_pdf(path: str) -> list[Document]:
    return PyPDFLoader(path).load()


def check_public_url(url: str) -> None:
    """Refuse URLs that resolve to private or local addresses, so the server can't be used to probe its own network."""
    host = urlparse(url).hostname or ""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        raise ValueError(f"Could not resolve host: {host}")
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if not ip.is_global:
            raise ValueError("URLs pointing to private or local addresses are not allowed.")


def load_url(url: str) -> list[Document]:
    check_public_url(url)
    return WebBaseLoader(url, requests_kwargs={"timeout": 20}).load()


def load_text(text: str) -> list[Document]:
    return [Document(page_content=text)]


def ingest(docs: list[Document], source: str, session_id: str) -> dict:
    """Chunk documents, embed them locally and store them in Chroma, tagged with the uploader's session."""
    if len(list_documents(session_id)) >= settings.max_docs_per_session:
        raise ValueError(f"Limit of {settings.max_docs_per_session} documents reached. Remove one first.")

    doc_id = uuid.uuid4().hex[:12]
    splitter = RecursiveCharacterTextSplitter(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    chunks = splitter.split_documents(docs)
    chunks = [c for c in chunks if c.page_content.strip()]
    if not chunks:
        raise ValueError("No readable text found in this document.")
    if len(chunks) > settings.max_chunks_per_doc:
        raise ValueError(f"Document is too long ({len(chunks)} chunks, limit {settings.max_chunks_per_doc}).")

    created_at = int(time.time())
    for c in chunks:
        page = c.metadata.get("page")
        c.metadata = {
            "doc_id": doc_id,
            "session_id": session_id,
            "created_at": created_at,
            "source": source,
            # PyPDFLoader pages are 0-based; store 1-based for display, -1 when not paged
            "page": page + 1 if isinstance(page, int) else -1,
        }

    get_store().add_documents(chunks, ids=[f"{doc_id}-{i}" for i in range(len(chunks))])
    return {"doc_id": doc_id, "source": source, "chunks": len(chunks), "expires_at": expires_at(created_at)}


def expires_at(created_at: int) -> int:
    return created_at + int(settings.doc_ttl_hours * 3600)


def list_documents(session_id: str) -> list[dict]:
    metadatas = get_store().get(where={"session_id": session_id}, include=["metadatas"])["metadatas"]
    docs: dict[str, dict] = {}
    for m in metadatas:
        d = docs.setdefault(
            m["doc_id"],
            {"doc_id": m["doc_id"], "source": m["source"], "chunks": 0, "expires_at": expires_at(m["created_at"])},
        )
        d["chunks"] += 1
    return list(docs.values())


def delete_document(session_id: str, doc_id: str) -> int:
    store = get_store()
    ids = store.get(where={"$and": [{"session_id": session_id}, {"doc_id": doc_id}]})["ids"]
    if ids:
        store.delete(ids=ids)
    return len(ids)


def purge_expired() -> int:
    """Delete every chunk older than doc_ttl_hours, across all sessions. Returns the number of chunks removed."""
    cutoff = int(time.time() - settings.doc_ttl_hours * 3600)
    store = get_store()
    ids = store.get(where={"created_at": {"$lt": cutoff}})["ids"]
    if ids:
        store.delete(ids=ids)
    return len(ids)


# ---------- Retrieval + grounded generation ----------

def retrieve(question: str, session_id: str) -> list[dict]:
    # Cosine distance is 0..2; unrelated chunks give negative similarity, so clamp to 0..1
    results = get_store().similarity_search_with_score(question, k=settings.top_k, filter={"session_id": session_id})
    return [
        {
            "n": i + 1,
            "source": doc.metadata["source"],
            "page": doc.metadata["page"],
            "score": round(max(0.0, 1.0 - distance), 3),
            "text": doc.page_content,
        }
        for i, (doc, distance) in enumerate(results)
    ]


def format_context(sources: list[dict]) -> str:
    parts = []
    for s in sources:
        where = f"{s['source']}, page {s['page']}" if s["page"] > 0 else s["source"]
        parts.append(f"[{s['n']}] ({where})\n{s['text']}")
    return "\n\n".join(parts)


def _text(content) -> str:
    # Some chat models return a list of content parts instead of a plain string
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)


def stream_answer(question: str, sources: list[dict]) -> Iterator[str]:
    messages = PROMPT.format_messages(context=format_context(sources), question=question)
    for chunk in get_llm().stream(messages):
        text = _text(chunk.content)
        if text:
            yield text
