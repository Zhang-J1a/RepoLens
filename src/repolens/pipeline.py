"""Question answering orchestration with bounded retrieval follow-ups."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import time
from typing import Any
import uuid

from repolens.answer import (
    StructuredAnswer,
    abstained_answer,
    answer_schema_document,
    validate_provider_output,
)
from repolens.context import ContextPack, EvidenceContextPacker
from repolens.domain import RepoLensError
from repolens.provider import Provider, ProviderRequest
from repolens.retrieval import identifier_terms


@dataclass(frozen=True)
class AnswerTelemetry:
    """Safe operational metadata for one bounded answer workflow."""

    trace_id: str
    provider: str
    model: str
    usage: Mapping[str, int]
    provider_request_id: str | None
    attempts: int
    duration_ms: int
    retrieval_rounds: int = 0
    generation_rounds: int = 0
    follow_up_searches: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trace_id, str)
            or not isinstance(self.provider, str)
            or not isinstance(self.model, str)
            or not self.trace_id.strip()
            or not self.provider.strip()
            or not self.model.strip()
        ):
            raise RepoLensError("Answer telemetry identifiers must not be empty.")
        if not isinstance(self.usage, Mapping):
            raise RepoLensError("Answer telemetry usage must be a JSON object.")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.usage.values()
        ):
            raise RepoLensError("Answer telemetry usage values must be non-negative integers.")
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) or self.attempts < 0:
            raise RepoLensError("Answer telemetry attempts must be a non-negative integer.")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise RepoLensError("Answer telemetry duration must be a non-negative integer.")
        for name, value in (
            ("retrieval rounds", self.retrieval_rounds),
            ("generation rounds", self.generation_rounds),
            ("follow-up searches", self.follow_up_searches),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RepoLensError(f"Answer telemetry {name} must be a non-negative integer.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "provider": self.provider,
            "model": self.model,
            "usage": dict(self.usage),
            "provider_request_id": self.provider_request_id,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
            "retrieval_rounds": self.retrieval_rounds,
            "generation_rounds": self.generation_rounds,
            "follow_up_searches": self.follow_up_searches,
        }


@dataclass(frozen=True)
class AnswerResult:
    question: str
    snapshot_id: str
    retrieval: tuple[Mapping[str, Any], ...]
    context: ContextPack
    answer: StructuredAnswer
    telemetry: AnswerTelemetry
    retrieval_queries: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        retrieval = []
        for item in self.retrieval:
            retrieval.append({
                key: item[key]
                for key in (
                    "evidence_id", "path", "symbol", "line_start", "line_end", "commit_sha",
                    "bm25_score", "vector_score", "hybrid_score", "keyword_rank", "vector_rank",
                    "retrieval_method",
                )
                if key in item
            })
        return {
            "question": self.question,
            "snapshot_id": self.snapshot_id,
            "retrieval": retrieval,
            "retrieval_queries": list(self.retrieval_queries),
            "context": self.context.to_dict(),
            "answer": self.answer.to_dict(),
            "telemetry": self.telemetry.to_dict(),
        }


class QuestionAnswerPipeline:
    """Retrieve, optionally follow up with bounded searches, and validate citations."""

    def __init__(
        self,
        store,
        snapshot_id: str,
        provider: Provider,
        *,
        context_packer: EvidenceContextPacker | None = None,
        max_output_tokens: int = 512,
        max_follow_up_searches: int = 0,
        retrieval_strategy: str = "keyword",
        retriever_factory=None,
    ):
        if not snapshot_id.strip():
            raise RepoLensError("Answer pipeline requires a snapshot ID.")
        if max_output_tokens < 1:
            raise RepoLensError("Answer output token budget must be positive.")
        if isinstance(max_follow_up_searches, bool) or not isinstance(max_follow_up_searches, int):
            raise RepoLensError("Answer follow-up search budget must be an integer.")
        if not 0 <= max_follow_up_searches <= 3:
            raise RepoLensError("Answer follow-up search budget must be between 0 and 3.")
        if retrieval_strategy not in ("keyword", "vector", "hybrid", "graph"):
            raise RepoLensError("Answer retrieval strategy must be keyword, vector, hybrid, or graph.")
        self.store = store
        self.snapshot_id = snapshot_id
        self.provider = provider
        self.context_packer = context_packer or EvidenceContextPacker()
        self.max_output_tokens = max_output_tokens
        self.max_follow_up_searches = max_follow_up_searches
        self.retrieval_strategy = retrieval_strategy
        self.retriever_factory = retriever_factory

    def answer(
        self,
        question: str,
        *,
        limit: int = 5,
        path_prefix: str | None = None,
        history: Sequence[Mapping[str, str]] = (),
    ) -> AnswerResult:
        if not question.strip():
            raise RepoLensError("Answer question must not be empty.")
        normalized_history = tuple(history[-8:])
        self._validate_history(normalized_history)
        retrieval_query = " ".join(
            [
                *(message["content"][:800] for message in normalized_history if message["role"] == "user"),
                question,
            ]
        )[:4096]
        trace_id = uuid.uuid4().hex
        started = time.perf_counter()
        retrieved: tuple[Mapping[str, Any], ...] = ()
        context = self.context_packer.pack(())
        retrieval_queries: list[str] = []
        used_queries: set[str] = set()
        response = None
        answer = None
        total_usage: dict[str, int] = {}
        total_attempts = 0
        retrieval_rounds = 0
        generation_rounds = 0
        follow_up_searches = 0
        retriever = (
            self.retriever_factory(
                store=self.store,
                snapshot_id=self.snapshot_id,
                strategy=self.retrieval_strategy,
                limit=limit,
                path_prefix=path_prefix,
            )
            if self.retriever_factory is not None else None
        )

        for round_index in range(self.max_follow_up_searches + 1):
            query = retrieval_query if round_index == 0 else self._follow_up_query(
                question,
                normalized_history,
                retrieved,
                used_queries,
            )
            if query is None:
                break
            used_queries.add(query)
            retrieval_queries.append(query)
            retrieval_rounds += 1
            search_method = {
                "keyword": "search",
                "vector": "search_vector",
                "hybrid": "search_hybrid",
                "graph": "search_graph",
            }[self.retrieval_strategy]
            if retriever is not None:
                found = tuple(
                    {**document.metadata, "text": document.page_content}
                    for document in retriever.invoke(query)
                )
            else:
                method = getattr(self.store, search_method, None)
                if method is None:
                    if self.retrieval_strategy != "keyword":
                        raise RepoLensError(
                            f"The selected store does not support {self.retrieval_strategy} retrieval."
                        )
                    method = self.store.search
                found = tuple(method(
                    query, self.snapshot_id, limit=limit, path_prefix=path_prefix,
                ))
            if round_index > 0:
                follow_up_searches += 1
            retrieved = self._merge_retrieval(found, retrieved)
            context = self.context_packer.pack(retrieved)
            if not context.items:
                continue

            request = ProviderRequest(
                question=question,
                context=context.rendered,
                evidence_ids=context.citation_ids,
                output_schema=answer_schema_document(),
                history=normalized_history,
                max_output_tokens=self.max_output_tokens,
                metadata={
                    "snapshot_id": self.snapshot_id,
                    "retrieval_count": str(len(retrieved)),
                    "packed_count": str(len(context.items)),
                    "trace_id": trace_id,
                    "retrieval_round": str(retrieval_rounds),
                },
            )
            generation_rounds += 1
            response = self.provider.generate(request)
            for key, value in response.usage.items():
                total_usage[key] = total_usage.get(key, 0) + value
            total_attempts += response.attempts
            answer = validate_provider_output(
                response.output,
                context,
                question,
                provider=response.provider,
                model=response.model,
                trace_id=trace_id,
            )
            if answer.status == "answered":
                break

        if answer is None:
            answer = abstained_answer(
                question,
                (
                    "检索到的证据均无法放入当前上下文预算，因此不生成事实性回答。"
                    if retrieved
                    else "未检索到属于当前 snapshot 的可验证证据，因此不生成事实性回答。"
                ),
                trace_id=trace_id,
            )
        return AnswerResult(
            question=question,
            snapshot_id=self.snapshot_id,
            retrieval=retrieved,
            context=context,
            answer=answer,
            telemetry=self._telemetry(
                trace_id,
                provider=response.provider if response else "none",
                model=response.model if response else "none",
                usage=total_usage,
                provider_request_id=response.request_id if response else None,
                attempts=total_attempts,
                started=started,
                retrieval_rounds=retrieval_rounds,
                generation_rounds=generation_rounds,
                follow_up_searches=follow_up_searches,
            ),
            retrieval_queries=tuple(retrieval_queries),
        )

    @staticmethod
    def _validate_history(history: Sequence[Mapping[str, str]]) -> None:
        if isinstance(history, (str, bytes)):
            raise RepoLensError("Answer conversation history must be an array.")
        for message in history:
            if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
                raise RepoLensError("Answer conversation messages must contain role and content only.")
            if message["role"] not in ("user", "assistant"):
                raise RepoLensError("Answer conversation message role must be user or assistant.")
            if not isinstance(message["content"], str) or not message["content"].strip():
                raise RepoLensError("Answer conversation message content must be non-empty text.")
            if len(message["content"]) > 2000:
                raise RepoLensError("Answer conversation message content must be at most 2000 characters.")

    @staticmethod
    def _merge_retrieval(new, previous) -> tuple[Mapping[str, Any], ...]:
        merged = []
        seen = set()
        for item in (*new, *previous):
            evidence_id = item.get("evidence_id")
            if evidence_id not in seen:
                seen.add(evidence_id)
                merged.append(item)
        return tuple(merged)

    @staticmethod
    def _follow_up_query(question, history, retrieved, used_queries):
        candidates = []
        for item in retrieved[:3]:
            if item.get("symbol"):
                candidates.append(item["symbol"])
            if item.get("path"):
                candidates.append(item["path"])
        search_text = " ".join(
            [question, *(message["content"] for message in history if message["role"] == "user")]
        )
        terms = identifier_terms(search_text)
        if terms:
            candidates.append(" ".join(terms))
        for candidate in candidates:
            candidate = str(candidate).strip()[:4096]
            if candidate and candidate not in used_queries:
                return candidate
        return None

    @staticmethod
    def _telemetry(
        trace_id: str,
        *,
        provider: str,
        model: str,
        started: float,
        usage: Mapping[str, int] | None = None,
        provider_request_id: str | None = None,
        attempts: int = 0,
        retrieval_rounds: int = 0,
        generation_rounds: int = 0,
        follow_up_searches: int = 0,
    ) -> AnswerTelemetry:
        return AnswerTelemetry(
            trace_id=trace_id,
            provider=provider,
            model=model,
            usage=dict(usage or {}),
            provider_request_id=provider_request_id,
            attempts=attempts,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            retrieval_rounds=retrieval_rounds,
            generation_rounds=generation_rounds,
            follow_up_searches=follow_up_searches,
        )
