import json
from collections.abc import AsyncIterator
from dotenv import load_dotenv

load_dotenv()  # must run before the clients below read their env vars

from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

from chat_tools import CHAT_TOOLS, decode_tool_arguments, read_file
from llm.base import LLMEvent, ToolCall
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
        "sent_chunks": [],
        "sent_chunk_keys": set(),
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

    tree_paths = {node.path for node in session["tree"] if node.type == "blob"}
    for path in req.context_files:
        if path not in tree_paths:
            raise HTTPException(status_code=400, detail=f"Pinned file is not in this repository: {path}")
        if path not in session["files"]:
            try:
                session["files"][path] = await github.get_file(
                    session["owner"], session["repo"], path,
                )
                session["chunks"].extend(parser.chunk_files({path: session["files"][path]}))
            except (ValueError, RuntimeError) as e:
                raise HTTPException(status_code=502, detail=f"Could not load pinned file {path}: {e}")

    provider_context_tokens = min(p.context_tokens for p in chain)
    stable_prompt = llm.build_system_prompt(
        session["owner"], session["repo"], session["tree"], [],
    )
    stable_chars = sum(len(block["text"]) for block in stable_prompt)
    sent_chars = sum(len(chunk.content) for chunk in session["sent_chunks"])
    history_chars = sum(len(message.get("content") or "") for message in session["history"])
    context_budget = max(
        provider_context_tokens - (stable_chars + sent_chars + history_chars) // 4,
        0,
    )
    relevant_chunks = parser.select_relevant_chunks(
        session["chunks"],
        req.prompt,
        context_files=req.context_files,
        max_tokens=context_budget,
    )

    for chunk in relevant_chunks:
        key = (chunk.path, chunk.start_line, chunk.end_line)
        if key not in session["sent_chunk_keys"]:
            session["sent_chunk_keys"].add(key)
            session["sent_chunks"].append(chunk)

    history = session["history"]
    system = llm.build_system_prompt(
        session["owner"], session["repo"], session["tree"], session["sent_chunks"],
    )
    messages = [*history, {"role": "user", "content": req.prompt}]

    # Errors before the first token become a proper HTTP error the UI can show.
    try:
        provider, first_token, rest, request_id = await llm.open_stream(
            chain, system, messages, feature="chat", session_id=req.session_id,
            tools=CHAT_TOOLS,
        )
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error — {e}")

    async def stream():
        full_response = ""
        current_provider = provider
        current_first = first_token
        current_rest = rest
        try:
            for _ in range(8):
                tool_calls = []
                round_text = ""
                if current_first is not None:
                    events = _with_first(current_first, current_rest)
                else:
                    events = current_rest
                async for event in events:
                    if isinstance(event, ToolCall):
                        tool_calls.append(event)
                    else:
                        round_text += event
                        full_response += event
                        yield event

                if not tool_calls:
                    history.append({"role": "user", "content": req.prompt})
                    history.append({"role": "assistant", "content": full_response})
                    if len(history) > 40:
                        session["history"] = history[-40:]
                    return

                messages.append({
                    "role": "assistant",
                    "content": round_text or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in tool_calls
                    ],
                })
                for call in tool_calls:
                    result = await _execute_chat_tool(session, call)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    })

                system = llm.build_system_prompt(
                    session["owner"], session["repo"], session["tree"], session["sent_chunks"],
                )
                current_provider, current_first, current_rest, _ = await llm.open_stream(
                    chain, system, messages, feature="chat", session_id=req.session_id,
                    tools=CHAT_TOOLS,
                )

            yield "\n\n[Stopped after too many consecutive tool calls.]"
        except llm.LLMError as e:
            yield f"\n\n[{current_provider.label} error: {e}]"
        finally:
            await current_rest.aclose()

    return StreamingResponse(
        stream(), media_type="text/plain", headers={"X-LLM-Request-Id": request_id},
    )


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"ok": True}


async def _with_first(
    first: LLMEvent,
    rest: AsyncIterator[LLMEvent],
) -> AsyncIterator[LLMEvent]:
    yield first
    async for event in rest:
        yield event


async def _execute_chat_tool(session: dict, call: ToolCall) -> str:
    arguments = decode_tool_arguments(call.arguments)
    if call.name == "read_file":
        path = arguments.get("path")
        if not isinstance(path, str):
            return "read_file requires a string path from the repository file tree."
        tree_paths = {
            node.path for node in session["tree"]
            if node.type == "blob"
        }
        if path not in tree_paths:
            return f"Path is not a file in this repository: {path}"

        try:
            content = session["files"].get(path)
            if content is None:
                content = await github.get_file(session["owner"], session["repo"], path)
                session["files"][path] = content
        except (ValueError, RuntimeError) as e:
            return f"Could not read {path}: {e}"

        start_line = arguments.get("start_line", 1)
        end_line = arguments.get("end_line")
        if not isinstance(start_line, int) or (end_line is not None and not isinstance(end_line, int)):
            return "start_line and end_line must be integers."
        return read_file(
            files={path: content},
            path=path,
            start_line=start_line,
            end_line=end_line,
        )

    if call.name == "search_code":
        query = arguments.get("query")
        if not isinstance(query, str):
            return "search_code requires a string query."
        return parser.search_code(session["files"], query)

    return f"Unknown tool: {call.name}"


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)