# RepoAI — Repo Administrator

An AI-powered administrator for your GitHub repositories: keep track of all your projects in one place, ask questions about their state, and get suggestions on how to improve them.

## Architecture

```
repo-admin/
├── backend/      Python + FastAPI  (port 8000)
└── frontend/     React + Vite      (port 5173)
```

## Quick Start

### Docker

Docker Compose runs the API and the production-built frontend together. Configure the
backend environment file before starting the stack:

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add your GITHUB_TOKEN

docker compose up --build
```

By default the stack also starts an `ollama` service and downloads the default open-weight model
(`gemma3:4b`, ~3.4 GB) on first run, so no LLM API key is needed. The container runs on CPU unless
you give it GPU access. If you use Claude or OpenAI instead, set `LLM_PROVIDER` in `backend/.env`
and start only what you need with `docker compose up --build backend frontend`.

- App: http://localhost:8080
- API and Swagger docs: http://localhost:8000/docs

The API database is stored in a named Docker volume and survives container restarts.
Stop the services with `docker compose down`; use `docker compose down -v` only when
you also want to delete the stored database.

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
# Edit .env and add your GITHUB_TOKEN

# Default LLM: a local open-weight model via Ollama (https://ollama.com)
ollama pull gemma3:4b

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
| `GITHUB_TOKEN` | ✅ | GitHub PAT — needed to list your repos; also raises the rate limit from 60 to 5,000 req/hr |
| `LLM_PROVIDER` | — | `ollama` (default), `anthropic` or `openai`. Aliases: `gemma` → `ollama`, `claude` → `anthropic` |
| `LLM_FALLBACK_PROVIDERS` | — | Comma-separated providers to try if the main one fails before responding |
| `LLM_MAX_TOKENS` | — | Max response tokens for every provider, defaults to `8000` |
| `OLLAMA_BASE_URL` | — | Defaults to `http://localhost:11434` |
| `OLLAMA_MODEL` | — | Defaults to `gemma3:4b` |
| `OLLAMA_NUM_CTX` | — | Context window, defaults to `32768`. Repo context is sized to fit it |
| `OLLAMA_NUM_GPU` | — | GPU layers; `0` forces CPU (no GPU, or CUDA driver errors) |
| `ANTHROPIC_API_KEY` | `anthropic` | Your Anthropic API key (`CLAUDE_API_KEY` is also accepted) |
| `CLAUDE_MODEL` | — | Defaults to `claude-sonnet-5-5` |
| `CLAUDE_MAX_TOKENS` | — | Defaults to `LLM_MAX_TOKENS` |
| `OPENAI_API_KEY` | `openai` | OpenAI key (optional for keyless local servers) |
| `OPENAI_MODEL` | `openai` | Model name — no default |
| `OPENAI_BASE_URL` | — | Defaults to `https://api.openai.com/v1`; set it for any OpenAI-compatible API (OpenRouter, Groq, vLLM, LM Studio...) |
| `DB_PATH` | — | SQLite file, defaults to `backend/repo_admin.db` |
| `LLM_USAGE_LOG` | — | Print one JSON line per LLM call to stdout, defaults to `true` |
| `LLM_PRICING_FILE` | — | JSON file adding or overriding model prices (see [LLM usage & cost tracing](#llm-usage--cost-tracing)) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Enables OpenTelemetry export, e.g. `http://localhost:4318` |
| `OTEL_SERVICE_NAME` | — | Service name on exported data, defaults to `repo-admin-backend` |

### Frontend (`frontend/.env`)

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend URL |

## How It Works

1. **Repos** — The Repos view lists every repository your `GITHUB_TOKEN` can see (owned, collaborator and org repos). Click **Sync from GitHub** to refresh it; the list is stored in SQLite so it survives restarts. Repos with no push in 90 days are flagged as stale.

2. **Load** — Click **Open** on a repo, or paste any GitHub URL and click Load. The backend fetches the repo's file tree and contents via the GitHub API, then chunks them into context-ready pieces.

3. **Pin files** — Click files in the tree sidebar to pin them to the context window. Pinned files are always included in the LLM prompt, regardless of relevance scoring.

4. **Chat** — Type a request in the chat panel. The backend selects relevant file chunks, builds a system prompt with the repo context, and streams the selected provider's response back token by token. Requests to list or count open issues fetch current issue records from GitHub; pull requests are excluded.

## LLM Providers

The default provider is a local open-weight model (Gemma via Ollama), so a fresh setup
costs nothing per token and needs no API key.

> **Upgrading from a Claude-only version?** Add `LLM_PROVIDER=anthropic` to `backend/.env`
> to keep using Claude.

- **Switching providers** — set `LLM_PROVIDER` (and that provider's model/key vars) and restart.
  `GET /llm/providers` shows the default, the fallbacks and which providers are configured.
- **Per-request override** — `POST /chat` accepts optional `provider` and `model` fields, e.g.
  `{"session_id": "...", "prompt": "...", "provider": "anthropic", "model": "claude-opus-5-5"}`.
- **Fallback** — with `LLM_FALLBACK_PROVIDERS=anthropic`, a request whose provider fails
  *before sending its first token* (unreachable, model missing, bad key) is retried on the next
  provider. Errors after streaming has started are shown inline at the end of the reply.

### Adding a provider

1. Create `backend/llm/<name>_provider.py` with a subclass of `LLMProvider` (`backend/llm/base.py`):
   - set `name` and `default_model`
   - implement `async def stream(self, system, messages, usage)` — `messages` is a list of
     `{"role": "user" | "assistant", "content": str}`; yield plain text tokens
   - fill in `usage` (`input_tokens` without cached tokens, `output_tokens`, `cache_read_tokens`,
     `cache_write_tokens`) from the provider's response. Fields you leave as `None` are estimated
     from text length and flagged `estimated`
   - raise `LLMError` with a readable message for failures the user should see
   - override `is_configured()` (required keys present) and `context_tokens` (repo-context budget) if needed
2. Register the class in `PROVIDERS` in `backend/llm/registry.py` (optionally add an alias in `ALIASES`).
3. Add its prices to `DEFAULT_PRICES` in `backend/llm/pricing.py` (or leave them to `LLM_PRICING_FILE`).
4. Document its env vars in `backend/.env.example` and the table above.

Tracing needs nothing else: every provider is wrapped by `llm/tracing.py` automatically.

## LLM usage & cost tracing

Every LLM call, for every provider and including failed fallback attempts, produces one
record with:

| Field | Meaning |
|---|---|
| `input_tokens`, `output_tokens` | Uncached input and output tokens, as reported by the provider |
| `cache_read_tokens`, `cache_write_tokens` | Prompt-cache tokens (billed at their own rates) |
| `estimated` | `true` when the provider didn't report counts and they were estimated (~4 chars/token) |
| `cost_usd` | Cost from the pricing table; `null` when the model has no known price |
| `latency_ms`, `ttft_ms` | Total duration and time to first token |
| `status`, `error` | `ok`, `error` or `cancelled` (client disconnected mid-stream) |
| `provider`, `model`, `feature`, `session_id` | Dimensions to aggregate on |
| `request_id`, `attempt` | Groups a request's primary and fallback attempts; returned to clients in the `X-LLM-Request-Id` header |

Where token counts come from: Claude → `usage` on the final message (including cache tokens);
Ollama → `prompt_eval_count` / `eval_count`; OpenAI-compatible → the `usage` chunk requested with
`stream_options.include_usage` (estimated if the server ignores it).

Each record goes to every **sink**. Sinks run after the stream ends, so they don't delay the
response, and a failing sink never fails a request:

- **SQLite** (always on) — query it through the API:
  - `GET /usage/summary?group_by=model&since=2026-10-01` — totals plus one row per group
    (`provider`, `model`, `feature`, `session`, `status` or `day`). Also filters by `session_id` / `provider`.
  - `GET /usage/calls?limit=50&provider=anthropic` — the most recent individual calls.
  - The info panel in the UI shows the current session's tokens and cost from this endpoint.
- **JSON log line** (on by default, `LLM_USAGE_LOG=false` to disable) — one
  `{"event": "llm_call", ...}` line per call on stdout, ready for Datadog, Loki, CloudWatch or
  any other log pipeline to parse and chart.
- **OpenTelemetry** (opt-in) — `pip install -r requirements-otel.txt` (or build the Docker image
  with `WITH_OTEL=true docker compose up --build`) and set `OTEL_EXPORTER_OTLP_ENDPOINT`. Each
  call becomes a `chat <model>` span plus metrics, using the GenAI semantic conventions:
  - span attributes `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
    `gen_ai.usage.output_tokens`, `llm.cost.usd`, `llm.time_to_first_token_ms`, `session.id`, …
  - metrics `gen_ai.client.token.usage` (by `gen_ai.token.type`), `gen_ai.client.operation.duration`,
    `llm.cost` (USD) and `llm.calls` (by `llm.status`)

  Point it at an OpenTelemetry Collector, or straight at the Datadog Agent's OTLP receiver
  (`http://<agent>:4318`), Grafana Alloy, Honeycomb, Jaeger, etc. Standard `OTEL_*` variables
  (headers, resource attributes) are honored.
- **Custom sinks** — `llm.add_sink(fn)` registers any `fn(CallRecord)`, e.g. to push to a
  queue or a billing system.

### Pricing

Built-in prices (USD per 1M tokens) live in `backend/llm/pricing.py`: Anthropic first-party rates
as of 2026-10-06 for the current Claude models, and `0` for every Ollama model. OpenAI and other
OpenAI-compatible models have no built-in price: their calls are tracked with `cost_usd: null`
(counted as `unpriced_calls` in summaries) until you add them. To add or override prices, point
`LLM_PRICING_FILE` at a JSON file. Keys are `provider/model`, or `provider/*` for every model
of a provider:

```json
{
  "openai/my-model": {"input": 1.25, "output": 10.0, "cache_read": 0.125},
  "anthropic/claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}
}
```

Costs are estimates from list prices. Your provider's invoice is the source of truth (it may
include discounts, batch rates, or long-context tiers that aren't modeled here).

## Key Design Decisions

### Context selection (`backend/repo_parser.py`)
Rather than stuffing the entire repo into the prompt (impossible for large repos), the backend scores each file chunk by keyword overlap with the user's prompt, prioritizing explicitly pinned files. The top chunks are greedily packed up to a token budget.

### Streaming
Responses stream token-by-token from the LLM provider → FastAPI `StreamingResponse` → `fetch` ReadableStream in the browser. The chat bubble updates live as tokens arrive.

### Session management
Repo context and conversation history are stored in-memory per `session_id` (a UUID generated on page load). For production, move this to Redis.

## Project Structure

```
backend/
├── main.py            FastAPI app and routes
├── db.py              SQLite storage for the repo list and LLM usage
├── models.py          Pydantic schemas
├── github_client.py   GitHub API — list repos, fetch tree + file contents
├── repo_parser.py     Chunk files, select relevant context
├── llm/               Provider-agnostic LLM layer
│   ├── base.py                LLMProvider interface + LLMError
│   ├── registry.py            Provider selection, aliases, fallback
│   ├── prompt.py              System prompt + repo context
│   ├── tracing.py             Per-call token/cost/latency records + sinks
│   ├── pricing.py             Price table (USD per 1M tokens)
│   ├── otel.py                Optional OpenTelemetry export
│   ├── ollama_provider.py     Ollama (open-weight, default)
│   ├── anthropic_provider.py  Claude
│   └── openai_provider.py     OpenAI / OpenAI-compatible
├── requirements.txt
└── requirements-otel.txt      Optional OpenTelemetry exporter

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
- **Apply patches**: Add a `POST /apply` endpoint that writes the model's suggested changes back to a local clone via `gitpython`.
- **Auth**: Add FastAPI dependency injection with API key or OAuth for multi-user deployments.
