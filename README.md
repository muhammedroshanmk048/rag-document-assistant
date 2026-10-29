# DocChat — RAG Document Assistant

A chatbot that answers questions using information retrieved from your PDFs, articles and internal documents — with inline citations back to the source and page.

Built to run **100% free**: local embeddings, a local vector database, and either the Gemini free tier or a fully offline Ollama model.

## How it works

```
Upload PDF / URL / text
        │
        ▼
 Load ─► Chunk (RecursiveCharacterTextSplitter, 1000 chars / 150 overlap)
        │
        ▼
 Embed locally (all-MiniLM-L6-v2 via fastembed/ONNX) ─► Store in Chroma
        
 Question ─► Embed ─► Vector search (top-k chunks) ─► Prompt with numbered context
                                                        │
                                                        ▼
                                  LLM (Gemini or Ollama) streams a grounded answer
                                  citing [1], [2]… → shown with source + page
```

**Skills covered:** document chunking, embeddings, vector search, retrieval, grounded generation, streaming (SSE).

## Tech stack

| Layer | Tool |
|---|---|
| API | Python, FastAPI, Pydantic |
| RAG pipeline | LangChain |
| Vector DB | Chroma (persisted to `data/chroma`) |
| Embeddings | `all-MiniLM-L6-v2` via fastembed (ONNX), runs locally on CPU, no PyTorch |
| LLM | Gemini (free tier) or Ollama (local) — switch with one env var |
| Frontend | Plain HTML/CSS/JS chat UI |
| Deploy | Docker, Render (free tier) |

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env          # then add your GOOGLE_API_KEY
uvicorn app.main:app --reload
```

Open http://localhost:8000 · API docs at http://localhost:8000/docs

Get a free Gemini key at [Google AI Studio](https://aistudio.google.com/apikey).

### Fully offline (no API key)

```bash
ollama pull llama3.2
```
Set `LLM_PROVIDER=ollama` in `.env`.

## API

Every `/api/documents*` and `/api/chat` request needs an `X-Session-Id` header (16–64 letters, digits or dashes). The UI generates a random one per browser.

| Method | Path | Description |
|---|---|---|
| POST | `/api/documents/upload` | Upload a `.pdf`, `.md` or `.txt` file |
| POST | `/api/documents/url` | Ingest a web article `{ "url": "..." }` |
| POST | `/api/documents/text` | Ingest raw text `{ "title": "...", "text": "..." }` |
| GET | `/api/documents` | List this session's documents |
| GET | `/api/limits` | Upload / document / expiry limits |
| DELETE | `/api/documents/{doc_id}` | Remove a document and its chunks |
| POST | `/api/chat` | Ask `{ "question": "..." }` — streams SSE events `sources`, `token`, `done` |

## Multi-user safety

Built to be deployed publicly without accounts:

- **Per-browser isolation** — each browser gets a random session ID; every chunk is tagged with it and listing, search and delete are filtered by it, so visitors never see each other's documents.
- **Auto-expiry** — documents are deleted after `DOC_TTL_HOURS` (default 24) by a background job, so storage can't pile up.
- **Limits** — max documents per session, upload size and chunks per document, and a per-IP rate limit on chat to protect the free LLM quota.
- **URL ingest guard** — URLs resolving to private/local addresses are refused.

All limits are configurable via environment variables (see `.env.example`).

## Deploy free on Render

The app is sized for Render's free web service (512 MB RAM, no credit card): embeddings run on ONNX instead of PyTorch with small batches, so even a 300-chunk document peaks around 360 MB.

1. Sign in at [render.com](https://render.com) with GitHub.
2. **New → Blueprint** → pick this repo. Render reads `render.yaml` and creates a free Docker web service.
3. Paste your `GOOGLE_API_KEY` when asked, then deploy.

Free-tier behaviour: the service sleeps after 15 minutes idle (the first request then takes about a minute), and its disk is temporary, so documents also reset on every restart or redeploy — on top of the 24h auto-expiry.

## Notes

- The Gemini free tier may use prompts to improve Google's models — use public documents, or Ollama for private ones.
- Embeddings are local, so switching LLM providers never requires re-indexing documents.
