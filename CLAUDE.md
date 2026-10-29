# CLAUDE.md

## What this project is

DocChat — a RAG-based document assistant (mini project). Users upload PDFs, Markdown/text, or article URLs, then chat with them; answers are grounded only in the documents and cite sources inline as [1], [2] with page numbers.

Owner: Muhammed Roshan M K, backend engineer (Python, FastAPI). This is a public portfolio project. Portfolio site lives in the sibling repo `../project-zap` (live at https://muhammedroshanmk.vercel.app) — add a project card there once this is deployed.

## Hard constraint: everything must stay free

The owner does not want any paid dependency that could block the project later. Decisions made for that reason:

- **Embeddings run locally** (`sentence-transformers/all-MiniLM-L6-v2` via `langchain-huggingface`). Never switch to a paid embeddings API — it would also force re-indexing.
- **Chroma** runs embedded, persisted to `data/chroma` (gitignored). No hosted vector DB.
- **LLM is swappable** via `LLM_PROVIDER` env var: `gemini` (Google AI Studio free-tier key) or `ollama` (local, offline). OpenAI was skipped because it has no free tier.
- **Hosting target: Hugging Face Spaces (Docker, free CPU)**. Not Vercel — serverless can't keep Chroma's files. README has the Spaces YAML header; Dockerfile serves on port 7860 as user 1000 with CPU-only torch.

## Layout

- `app/config.py` — pydantic-settings, reads `.env`
- `app/rag.py` — loaders (PDF/URL/text), chunking, Chroma store, retrieval, grounded prompt, streaming
- `app/main.py` — FastAPI routes; `/api/chat` streams SSE events `sources`, `token`, `error`, `done`
- `static/` — plain HTML/CSS/JS chat UI (dark theme matching the portfolio), served at `/`
- `Dockerfile`, `requirements.txt`, `.env.example`, `README.md`

## Status (as of 2026-10-29)

Done:
- Deps installed in `.venv`; `.env` created (gitignored, also in `.dockerignore`).
- Tested end to end locally: PDF upload, URL ingest, text ingest, delete, chat with citations, out-of-scope refusal.
- Fixes from testing: `gemini-2.5-flash` was retired for new keys -> now `gemini-flash-latest` alias, with `GEMINI_FALLBACK_MODEL=gemini-flash-lite-latest` and `max_retries=1` because the free tier returns 503 at peak times. Chroma collection uses cosine distance so relevance scores stay in 0..1 (delete `data/chroma` if an old L2 store exists).
- Versions pinned in `requirements.txt` (torch pinned in Dockerfile/README). Pushed to https://github.com/muhammedroshanmk048/rag-document-assistant (`origin/main`).

Not done yet, in order:
0. Before public deploy: all visitors share one Chroma store (no per-user isolation) and HF free-tier disk resets on restart. Owner was told; per-session isolation was offered, not yet decided.
1. Deploy to Hugging Face Spaces, add `GOOGLE_API_KEY` as a Space secret. Docker image build has not been tested locally (Docker Desktop was not running).
2. Add a DocChat card to the portfolio in `../project-zap/index.html` and push (Vercel auto-deploys).

## Environment notes

- Windows 11, Python 3.13 locally (Docker image uses 3.11). Shell: PowerShell or Git Bash.
- Commit messages end with a `Co-Authored-By` line; ask before pushing.
