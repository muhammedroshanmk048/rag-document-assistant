---
title: DocChat RAG Document Assistant
emoji: 📄
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

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
 Embed locally (sentence-transformers/all-MiniLM-L6-v2) ─► Store in Chroma
        
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
| Embeddings | HuggingFace `all-MiniLM-L6-v2`, runs locally on CPU |
| LLM | Gemini (free tier) or Ollama (local) — switch with one env var |
| Frontend | Plain HTML/CSS/JS chat UI |
| Deploy | Docker, Hugging Face Spaces |

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
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

| Method | Path | Description |
|---|---|---|
| POST | `/api/documents/upload` | Upload a `.pdf`, `.md` or `.txt` file |
| POST | `/api/documents/url` | Ingest a web article `{ "url": "..." }` |
| POST | `/api/documents/text` | Ingest raw text `{ "title": "...", "text": "..." }` |
| GET | `/api/documents` | List ingested documents |
| DELETE | `/api/documents/{doc_id}` | Remove a document and its chunks |
| POST | `/api/chat` | Ask `{ "question": "..." }` — streams SSE events `sources`, `token`, `done` |

## Deploy free on Hugging Face Spaces

1. Create a new Space → SDK **Docker** → Blank.
2. Push this repo to the Space (or connect it to GitHub).
3. In Space **Settings → Variables and secrets**, add secret `GOOGLE_API_KEY`.

Note: free Spaces storage is temporary, so uploaded documents reset when the Space restarts.

## Notes

- The Gemini free tier may use prompts to improve Google's models — use public documents, or Ollama for private ones.
- Embeddings are local, so switching LLM providers never requires re-indexing documents.
