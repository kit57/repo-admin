# RepoAI — Repo Administrator

An AI-powered administrator for your GitHub repositories: keep track of all your projects in one place, ask questions about their state, and get suggestions on how to improve them.

## Architecture

```
repo-admin/
├── backend/      Python + FastAPI  (port 8000)
└── frontend/     React + Vite      (port 5173)
```

## Quick Start

### 1. Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY and GITHUB_TOKEN

# Run
python main.py
# → API available at http://localhost:8000
# → Swagger docs at http://localhost:8000/docs
```

### 2. Frontend

```bash
cd frontend

npm install

cp .env.example .env   # adjust VITE_API_URL if needed

npm run dev
# → App available at http://localhost:5173
```

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Your Anthropic API key (`CLAUDE_API_KEY` is also accepted) |
| `GITHUB_TOKEN` | ✅ | GitHub PAT — needed to list your repos; also raises the rate limit from 60 to 5,000 req/hr |
| `CLAUDE_MODEL` | — | Defaults to `claude-sonnet-5-5` |
| `CLAUDE_MAX_TOKENS` | — | Defaults to `8000` |
| `DB_PATH` | — | SQLite file, defaults to `backend/repo_admin.db` |

### Frontend (`frontend/.env`)

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend URL |

## How It Works

1. **Repos** — The Repos view lists every repository your `GITHUB_TOKEN` can see (owned, collaborator and org repos). Click **Sync from GitHub** to refresh it; the list is stored in SQLite so it survives restarts. Repos with no push in 90 days are flagged as stale.

2. **Load** — Click **Open** on a repo, or paste any GitHub URL and click Load. The backend fetches the repo's file tree and contents via the GitHub API, then chunks them into context-ready pieces.

3. **Pin files** — Click files in the tree sidebar to pin them to the context window. Pinned files are always included in the Claude prompt, regardless of relevance scoring.

4. **Chat** — Type a request in the chat panel. The backend selects the most relevant file chunks (up to ~60k tokens), builds a system prompt with the repo context, and streams Claude's response back token by token.

## Key Design Decisions

### Context selection (`backend/repo_parser.py`)
Rather than stuffing the entire repo into the prompt (impossible for large repos), the backend scores each file chunk by keyword overlap with the user's prompt, prioritizing explicitly pinned files. The top chunks are greedily packed up to a token budget.

### Streaming
Responses stream token-by-token from Claude → FastAPI `StreamingResponse` → `fetch` ReadableStream in the browser. The chat bubble updates live as tokens arrive.

### Session management
Repo context and conversation history are stored in-memory per `session_id` (a UUID generated on page load). For production, move this to Redis.

## Project Structure

```
backend/
├── main.py            FastAPI app and routes
├── db.py              SQLite storage for the repo list
├── models.py          Pydantic schemas
├── github_client.py   GitHub API — list repos, fetch tree + file contents
├── repo_parser.py     Chunk files, select relevant context
├── claude_client.py   Anthropic streaming client
└── requirements.txt

frontend/src/
├── main.jsx                   Entry point
├── App.jsx                    Root layout + state wiring
├── index.css                  Global styles
├── api/client.js              fetch wrappers for all backend calls
├── utils/time.js              Relative time helpers
├── hooks/useSession.js        Session state + load/chat actions
└── components/
    ├── RepoList.jsx            All repos table + sync
    ├── FileTree.jsx            Sidebar file explorer (recursive)
    ├── ChatPanel.jsx           Messages + streaming input
    └── InfoPanel.jsx           Repo stats + session info
```

## Extending

- **Vector search**: Replace keyword scoring in `repo_parser.py` with embeddings (e.g. `sentence-transformers` + FAISS) for better chunk retrieval on large repos.
- **Private repos**: Already supported — add a `GITHUB_TOKEN` with `repo` scope.
- **Apply patches**: Add a `POST /apply` endpoint that writes Claude's suggested changes back to a local clone via `gitpython`.
- **Auth**: Add FastAPI dependency injection with API key or OAuth for multi-user deployments.
