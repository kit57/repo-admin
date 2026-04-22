from pydantic import BaseModel, field_validator
from typing import Optional
import uuid


class LoadRepoRequest(BaseModel):
    url: str
    session_id: str = ""
    max_files: int = 300

    @field_validator("session_id", mode="before")
    @classmethod
    def set_session_id(cls, v):
        return v or str(uuid.uuid4())

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if "github.com" not in v:
            raise ValueError("Only GitHub URLs are supported")
        return v.strip().rstrip("/")


class ChatRequest(BaseModel):
    session_id: str
    prompt: str
    context_files: list[str] = []  # filenames to prioritize in context


class TreeNode(BaseModel):
    path: str
    type: str  # "blob" | "tree"
    size: Optional[int] = None


class RepoMeta(BaseModel):
    full_name: str
    description: Optional[str] = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    default_branch: str = "main"
    language: Optional[str] = None
    languages: dict[str, int] = {}
    last_push: Optional[str] = None


class LoadRepoResponse(BaseModel):
    session_id: str
    file_count: int
    tree: list[TreeNode]
    meta: RepoMeta


class TreeResponse(BaseModel):
    tree: list[TreeNode]
    repo: str
    owner: str