from dotenv import load_dotenv

load_dotenv()  # must run before the clients below read their env vars

from dataclasses import asdict
import json
import re
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

from models import (
    LoadRepoRequest, ChatRequest, LoadRepoResponse, TreeResponse, RepoListResponse, ProvidersResponse,
    LLMCallsResponse, UsageSummaryResponse,
)
from github_client import GitHubClient
from repo_parser import RepoParser
import llm
import db

app = FastAPI(title="Repo Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-LLM-Request-Id"],
)

# In-memory session store: session_id -> parsed repo context
sessions: dict[str, dict] = {}


def _is_open_issue_list_request(prompt: str) -> bool:
    mentions_issues = re.search(r"\bissues?\b", prompt, re.IGNORECASE)
    requests_list = re.search(
        r"\b(open|opened|list|show|fetch|find|display|retrieve|how many|count)\b",
        prompt,
        re.IGNORECASE,
    )
    return bool(mentions_issues and requests_list)


github = GitHubClient()
parser = RepoParser()
# Resolve both at startup so a misspelled LLM_PROVIDER / LLM_FALLBACK_PROVIDERS fails fast.
default_llm = llm.get_provider()
llm.fallback_provider_names()

db.init_db()
# Every LLM call is logged as JSON, stored in SQLite and, if configured, exported via OpenTelemetry.
llm.configure_tracing(extra_sinks=[lambda call: db.insert_llm_call(asdict(call))])


@app.get("/usage/calls", response_model=LLMCallsResponse)
async def list_llm_calls(
    limit: int = Query(100, ge=1, le=1000),
    since: str | None = Query(None, description="ISO date/time (UTC), e.g. 2026-10-01"),
    session_id: str | None = None,
    provider: str | None = None,
):
    """Most recent LLM calls with their token counts, cost and latency."""
    return LLMCallsResponse(calls=db.list_llm_calls(limit, since, session_id, provider))


@app.get("/usage/summary", response_model=UsageSummaryResponse)
async def usage_summary(
    group_by: Literal["provider", "model", "feature", "session", "status", "day"] | None = None,
    since: str | None = Query(None, description="ISO date/time (UTC), e.g. 2026-10-01"),
    session_id: str | None = None,
    provider: str | None = None,
):
    """Aggregated token usage and cost, in total and optionally grouped."""
    summary = db.summarize_llm_calls(group_by, since, session_id, provider)
    return UsageSummaryResponse(group_by=group_by, **summary)


@app.get("/llm/providers", response_model=ProvidersResponse)
async def list_providers():
    """Return the configured default/fallback providers and every provider the API supports."""
    return ProvidersResponse(
        default_provider=default_llm.name,
        default_model=default_llm.model,
        fallback_providers=llm.fallback_provider_names(),
        providers=llm.describe_providers(),
    )


@app.get("/repos", response_model=RepoListResponse)
async def list_repos():
    """Return the stored list of the user's repositories."""
    return RepoListResponse(repos=db.list_repos(), synced_at=db.last_synced_at())


@app.post("/repos/sync", response_model=RepoListResponse)
async def sync_repos():
    """Refresh the stored repo list from GitHub."""
    try:
        repos = await github.list_user_repos()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")

    synced_at = db.replace_repos(repos)
    return RepoListResponse(repos=db.list_repos(), synced_at=synced_at)


@app.post("/repo/load", response_model=LoadRepoResponse)
async def load_repo(req: LoadRepoRequest):
    """Fetch and index a GitHub repository."""
    try:
        owner, repo_name = github.parse_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tree = await github.get_tree(owner, repo_name)
        files = await github.get_files(owner, repo_name, tree, max_files=req.max_files)
        meta = await github.get_repo_meta(owner, repo_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}")

    chunks = parser.chunk_files(files)

    sessions[req.session_id] = {
        "owner": owner,
        "repo": repo_name,
        "tree": tree,
        "files": files,
        "chunks": chunks,
        "meta": meta,
        "history": [],
    }

    return LoadRepoResponse(
        session_id=req.session_id,
        file_count=len(files),
        tree=tree[:200],  # send first 200 tree entries to frontend
        meta=meta,
        provider=default_llm.name,
        model=default_llm.model,
    )


@app.get("/repo/tree/{session_id}", response_model=TreeResponse)
async def get_tree(session_id: str):
    """Return the file tree for a loaded repo."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return TreeResponse(tree=session["tree"], repo=session["repo"], owner=session["owner"])


@app.post("/chat")
async def chat(req: ChatRequest):
    """Stream a code generation response from the selected LLM provider."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found — load a repo first")

    try:
        chain = llm.provider_chain(req.provider, req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    relevant_chunks = parser.select_relevant_chunks(
        session["chunks"],
        req.prompt,
        context_files=req.context_files,
        # A fallback may have a smaller context window than the primary provider.
        max_tokens=min(p.context_tokens for p in chain),
    )

    history = session["history"]
    system = llm.build_system_prompt(session["owner"], session["repo"], relevant_chunks)
    if _is_open_issue_list_request(req.prompt):
        try:
            issues = await github.get_open_issues(session["owner"], session["repo"])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"GitHub API error while fetching open issues: {e}")

        issue_records = [
            {
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["html_url"],
                "author": issue.get("user", {}).get("login"),
                "updated_at": issue.get("updated_at"),
            }
            for issue in issues
        ]
        system += (
            "\n\n## Live GitHub Open Issues\n"
            "The following records were fetched from GitHub for this repository when this message was received. "
            "They contain issues only, not pull requests. Use these records for issue counts and links; do not "
            "invent or supplement issue details.\n"
            f"Open issue count: {len(issue_records)}\n"
            f"Issues: {json.dumps(issue_records, ensure_ascii=False)}"
        )
    messages = [*history, {"role": "user", "content": req.prompt}]
    request_id = str(uuid.uuid4())

    async def stream():
        provider = None
        rest = None
        full_response = ""
        completed = False
        try:
            # Start the HTTP response before waiting for the provider's first token,
            # so the client can cancel even while the model is still thinking.
            try:
                provider, first_token, rest, _ = await llm.open_stream(
                    chain, system, messages, feature="chat", session_id=req.session_id,
                    request_id=request_id,
                )
            except llm.LLMError as e:
                yield f"Error: LLM error — {e}"
                return

            full_response = first_token
            if first_token:
                yield first_token
            async for token in rest:
                full_response += token
                yield token
            completed = True
        except llm.LLMError as e:
            yield f"\n\n[{provider.label} error: {e}]"
        finally:
            if rest is not None:
                await rest.aclose()

        if completed:
            history.append({"role": "user", "content": req.prompt})
            history.append({"role": "assistant", "content": full_response})
            # Keep history bounded
            if len(history) > 40:
                session["history"] = history[-40:]

    return StreamingResponse(
        stream(), media_type="text/plain", headers={"X-LLM-Request-Id": request_id},
    )


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)