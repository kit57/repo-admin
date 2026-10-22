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
    provider: Optional[str] = None  # overrides LLM_PROVIDER for this request
    model: Optional[str] = None  # overrides the provider's default model


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
    provider: str
    model: str


class ProviderInfo(BaseModel):
    name: str
    default_model: str
    configured: bool


class ProvidersResponse(BaseModel):
    default_provider: str
    default_model: str
    fallback_providers: list[str]
    providers: list[ProviderInfo]


class TreeResponse(BaseModel):
    tree: list[TreeNode]
    repo: str
    owner: str


class RepoSummary(BaseModel):
    id: int
    full_name: str
    owner: str
    name: str
    description: Optional[str] = None
    html_url: str
    private: bool = False
    fork: bool = False
    archived: bool = False
    language: Optional[str] = None
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    default_branch: Optional[str] = None
    pushed_at: Optional[str] = None
    updated_at: Optional[str] = None
    synced_at: Optional[str] = None


class RepoListResponse(BaseModel):
    repos: list[RepoSummary]
    synced_at: Optional[str] = None


class LLMCall(BaseModel):
    id: str
    request_id: str
    started_at: str
    provider: str
    model: str
    feature: str
    session_id: Optional[str] = None
    attempt: int
    status: str  # "ok" | "error" | "cancelled"
    error: Optional[str] = None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    estimated: bool
    cost_usd: Optional[float] = None  # None when the model has no known price
    latency_ms: float
    ttft_ms: Optional[float] = None


class LLMCallsResponse(BaseModel):
    calls: list[LLMCall]


class UsageStats(BaseModel):
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float  # sum over priced calls
    unpriced_calls: int  # calls whose model has no known price (not included in cost_usd)
    estimated_calls: int
    avg_latency_ms: Optional[float] = None
    avg_ttft_ms: Optional[float] = None


class UsageGroup(UsageStats):
    key: Optional[str] = None


class UsageSummaryResponse(BaseModel):
    group_by: Optional[str] = None
    total: UsageStats
    groups: list[UsageGroup]
