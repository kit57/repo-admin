from dotenv import load_dotenv

load_dotenv()  # must run before the clients below read their env vars

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

from models import LoadRepoRequest, ChatRequest, LoadRepoResponse, TreeResponse, RepoListResponse
from github_client import GitHubClient
from repo_parser import RepoParser
from claude_client import ClaudeClient, MODEL
import db

app = FastAPI(title="Repo Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store: session_id -> parsed repo context
sessions: dict[str, dict] = {}

github = GitHubClient()
parser = RepoParser()
claude = ClaudeClient()

db.init_db()


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
        model=MODEL,
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
    """Stream a code generation response from Claude."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found — load a repo first")

    relevant_chunks = parser.select_relevant_chunks(
        session["chunks"],
        req.prompt,
        context_files=req.context_files,
        max_tokens=60_000,
    )

    history = session["history"]

    async def stream():
        full_response = ""
        async for token in claude.stream(
            repo_owner=session["owner"],
            repo_name=session["repo"],
            relevant_chunks=relevant_chunks,
            history=history,
            user_message=req.prompt,
        ):
            full_response += token
            yield token

        history.append({"role": "user", "content": req.prompt})
        history.append({"role": "assistant", "content": full_response})
        # Keep history bounded
        if len(history) > 40:
            session["history"] = history[-40:]

    return StreamingResponse(stream(), media_type="text/plain")


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)