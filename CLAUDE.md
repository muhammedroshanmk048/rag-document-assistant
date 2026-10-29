# CLAUDE.md

## What this project is

DocChat — a RAG-based document assistant (mini project). Users upload PDFs, Markdown/text, or article URLs, then chat with them; answers are grounded only in the documents and cite sources inline as [1], [2] with page numbers.

Owner: Muhammed Roshan M K, backend engineer (Python, FastAPI). This is a public portfolio project. Portfolio site lives in the sibling repo `../project-zap` (live at https://muhammedroshanmk.vercel.app) — add a project card there once this is deployed.

## Hard constraint: everything must stay free

The owner does not want any paid dependency that could block the project later. Decisions made for that reason:

- **Embeddings run locally** (`sentence-transformers/all-MiniLM-L6-v2` via `fastembed`/ONNX, no PyTorch). Never switch to a paid embeddings API — it would also force re-indexing. Keep `embed_batch_size` small: fastembed's default 256 peaked near 2 GB on a 300-chunk doc; 4 peaks ~330 MB and is also faster.
- **Chroma** runs embedded, persisted to `data/chroma` (gitignored). No hosted vector DB.
- **LLM is swappable** via `LLM_PROVIDER` env var: `gemini` (Google AI Studio free-tier key) or `ollama` (local, offline). OpenAI was skipped because it has no free tier.
- **Hosting target: Render free web service (Docker, 512 MB RAM, no card)** via `render.yaml`. Hugging Face Spaces was the original plan but since mid-2026 Docker/Gradio Spaces need PRO for new accounts. Not Vercel — serverless can't run the embedding model. Dockerfile bakes the model into the image and serves on `$PORT`. Memory budget is the main constraint: measured peak ~364 MB.

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
- Versions pinned in `requirements.txt` . Pushed to https://github.com/muhammedroshanmk048/rag-document-assistant (`origin/main`).
- Multi-user safety (no login, by design): browser-generated `X-Session-Id` tags every chunk and filters list/search/delete; background TTL purge (`DOC_TTL_HOURS`); per-session doc cap, per-doc chunk cap, per-IP chat rate limit; URL ingest refuses private/local IPs. Chunks without `session_id`/`created_at` (from older builds) are invisible and never purged — wipe `data/chroma` if any exist.

- Live on Render: https://docchat-ft5u.onrender.com (auto-deploys from `main`). Verified live: upload, URL ingest, cited answers, refusal, session isolation, SSRF guard.
- DocChat card added to the portfolio (`../project-zap`, live at https://muhammedroshanmk.vercel.app).

All original steps are done. Possible next ideas (not requested): keep-warm ping to avoid the cold start, Ollama-free fallback if Gemini quota runs out.

## Environment notes

- Windows 11, Python 3.13 locally (Docker image uses 3.11). Shell: PowerShell or Git Bash.
- Commit messages end with a `Co-Authored-By` line; ask before pushing.
