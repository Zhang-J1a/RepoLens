"""Closed input contracts used by OpenAPI and generated TypeScript types."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Strategy = Literal["keyword", "vector", "hybrid", "graph"]
ModelProvider = Literal["mock", "deepseek", "langchain"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImportInput(ClosedModel):
    action: Literal["import"]
    repository: Text
    ref: Ref = "HEAD"


class Selection(ClosedModel):
    workspace_id: Text
    ref: Ref = "HEAD"


class SearchInput(Selection):
    action: Literal["search"]
    query: Text
    retrieval: Strategy = "hybrid"
    limit: int = Field(default=10, ge=1, le=100)
    path_prefix: str = Field(default="", max_length=4096)


class AskInput(Selection):
    action: Literal["ask"]
    question: Text
    retrieval: Strategy = "hybrid"
    provider: ModelProvider = "mock"
    max_follow_ups: int = Field(default=1, ge=0, le=3)


class ImpactInput(Selection):
    action: Literal["impact"]
    base: Ref
    provider: ModelProvider = "mock"
    with_graph: bool = True
    diff: str = Field(default="", max_length=100000)


class GraphInput(Selection):
    action: Literal["graph"]
    seed_kind: Literal["symbol", "path", "commit"] = "symbol"
    seed: str = Field(default="", max_length=4096)
    hops: int = Field(default=2, ge=1, le=2)


class AgentInput(Selection):
    action: Literal["agent"]
    question: Text
    base: str = Field(default="", max_length=512)
    provider: ModelProvider = "mock"
    max_steps: int = Field(default=8, ge=1, le=32)
    timeout_seconds: int = Field(default=120, ge=1, le=600)


TaskInput = Annotated[ImportInput | SearchInput | AskInput | ImpactInput | GraphInput | AgentInput,
                      Field(discriminator="action")]


class KeyInput(ClosedModel):
    api_key: str = Field(max_length=4096)


class SourceInput(ClosedModel):
    workspace_id: Text
    snapshot_id: Text
    path: Text
    evidence_id: str = Field(default="", max_length=512)


class DiffInput(ClosedModel):
    workspace_id: Text
    base_snapshot_id: Text
    head_snapshot_id: Text
    path: Text


class Workspace(ClosedModel):
    workspace_id: str
    name: str
    repository: str
    snapshots: list[dict]


class TaskView(ClosedModel):
    id: str
    action: str
    workspace_id: str | None
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    duration_ms: int
    events: list[dict]
    error: str | None
    result: dict | None
    request_id: str = "-"
    error_code: str | None = None


class Health(ClosedModel):
    ok: bool
    version: str
    stage: Literal["V6"] = "V6"
    key_configured: bool
    data_dir: str
