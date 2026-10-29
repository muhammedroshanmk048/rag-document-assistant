import asyncio
import json
import logging
import re
import tempfile
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app import rag
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rag")
settings = get_settings()
STATIC = Path(__file__).resolve().parent.parent / "static"


async def cleanup_loop():
    """Delete expired documents periodically so storage doesn't pile up on a public deployment."""
    while True:
        try:
            removed = await asyncio.to_thread(rag.purge_expired)
            if removed:
                log.info("Cleanup removed %d expired chunks", removed)
        except Exception:
            log.exception("Cleanup failed")
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the embedding model once at startup so the first request isn't slow
    rag.get_store()
    log.info("Embedding model and vector store ready (LLM provider: %s)", settings.llm_provider)
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="RAG Document Assistant", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- Sessions + rate limiting ----------

SESSION_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def session_id(x_session_id: Annotated[str, Header()]) -> str:
    """Each browser sends a random ID; documents are only visible to the session that added them."""
    if not SESSION_RE.match(x_session_id):
        raise HTTPException(400, "Invalid session id")
    return x_session_id


Session = Annotated[str, Depends(session_id)]

_chat_calls: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    # Hugging Face Spaces sits behind a proxy, so the real client is the first X-Forwarded-For hop
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def chat_rate_limit(request: Request) -> None:
    """Sliding one-minute window per client IP, to protect the shared free-tier LLM quota."""
    now = time.monotonic()
    calls = _chat_calls[client_ip(request)]
    while calls and now - calls[0] > 60:
        calls.popleft()
    if len(calls) >= settings.chat_requests_per_minute:
        raise HTTPException(429, "Too many questions — please wait a minute.")
    calls.append(now)
    # Drop idle clients so the table doesn't grow forever
    for ip in [ip for ip, c in _chat_calls.items() if not c or now - c[-1] > 60]:
        del _chat_calls[ip]


# ---------- Routes ----------

class UrlIn(BaseModel):
    url: HttpUrl


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.get("/api/limits")
def limits():
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_docs_per_session": settings.max_docs_per_session,
        "doc_ttl_hours": settings.doc_ttl_hours,
    }


@app.post("/api/documents/upload")
def upload(file: UploadFile, sid: Session):
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {settings.max_upload_mb} MB")

    try:
        if suffix == ".pdf":
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
            try:
                docs = rag.load_pdf(tmp.name)
            finally:
                Path(tmp.name).unlink(missing_ok=True)
        elif suffix in {".md", ".txt"}:
            docs = rag.load_text(data.decode("utf-8", errors="ignore"))
        else:
            raise HTTPException(400, "Only .pdf, .md and .txt files are supported")
        return rag.ingest(docs, source=name, session_id=sid)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/documents/url")
def add_url(body: UrlIn, sid: Session):
    try:
        docs = rag.load_url(str(body.url))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not fetch URL: {e}")
    try:
        return rag.ingest(docs, source=str(body.url), session_id=sid)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/documents/text")
def add_text(body: TextIn, sid: Session):
    try:
        return rag.ingest(rag.load_text(body.text), source=body.title, session_id=sid)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/documents")
def documents(sid: Session):
    return rag.list_documents(sid)


@app.delete("/api/documents/{doc_id}")
def remove(doc_id: str, sid: Session):
    if not rag.delete_document(sid, doc_id):
        raise HTTPException(404, "Document not found")
    return {"deleted": doc_id}


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/chat", dependencies=[Depends(chat_rate_limit)])
def chat(body: ChatIn, sid: Session):
    """Retrieve relevant chunks, then stream a grounded answer as server-sent events."""
    sources = rag.retrieve(body.question, sid)

    def events():
        if not sources:
            yield sse("token", "No documents yet — upload a PDF or add a URL first.")
            yield sse("done", {})
            return
        yield sse("sources", sources)
        try:
            for token in rag.stream_answer(body.question, sources):
                yield sse("token", token)
        except Exception as e:
            log.exception("LLM call failed")
            yield sse("error", str(e))
        yield sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream")
