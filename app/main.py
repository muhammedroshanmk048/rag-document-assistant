import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app import rag
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rag")
settings = get_settings()
STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the embedding model once at startup so the first request isn't slow
    rag.get_store()
    log.info("Embedding model and vector store ready (LLM provider: %s)", settings.llm_provider)
    yield


app = FastAPI(title="RAG Document Assistant", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class UrlIn(BaseModel):
    url: HttpUrl


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.post("/api/documents/upload")
def upload(file: UploadFile):
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    data = file.file.read()
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
        return rag.ingest(docs, source=name)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/documents/url")
def add_url(body: UrlIn):
    try:
        docs = rag.load_url(str(body.url))
    except Exception as e:
        raise HTTPException(400, f"Could not fetch URL: {e}")
    try:
        return rag.ingest(docs, source=str(body.url))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/documents/text")
def add_text(body: TextIn):
    try:
        return rag.ingest(rag.load_text(body.text), source=body.title)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/documents")
def documents():
    return rag.list_documents()


@app.delete("/api/documents/{doc_id}")
def remove(doc_id: str):
    if not rag.delete_document(doc_id):
        raise HTTPException(404, "Document not found")
    return {"deleted": doc_id}


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/chat")
def chat(body: ChatIn):
    """Retrieve relevant chunks, then stream a grounded answer as server-sent events."""
    sources = rag.retrieve(body.question)

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
