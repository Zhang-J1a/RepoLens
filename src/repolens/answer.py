"""Strict answer schema and citation validation for V2."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, Literal
import uuid

from repolens.context import ContextPack, PackedEvidence
from repolens.domain import RepoLensError


ANSWER_SCHEMA_VERSION = "repolens.answer.v1"
AnswerStatus = Literal["answered", "abstained"]
_ALLOWED_PROVIDER_FIELDS = {"status", "summary", "claims", "unknowns"}
MAX_SUMMARY_LENGTH = 4000
MAX_CLAIMS = 64
MAX_CLAIM_LENGTH = 4000
MAX_CITATIONS_PER_CLAIM = 32
MAX_UNKNOWNS = 32
MAX_UNKNOWN_LENGTH = 1000


def answer_schema() -> dict[str, Any]:
    """Return the JSON schema sent to a future provider."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ANSWER_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "summary", "claims", "unknowns"],
        "oneOf": [
            {
                "properties": {
                    "status": {"const": "answered"},
                    "claims": {"minItems": 1, "maxItems": MAX_CLAIMS},
                },
            },
            {
                "properties": {
                    "status": {"const": "abstained"},
                    "claims": {"maxItems": 0},
                    "unknowns": {"minItems": 1, "maxItems": MAX_UNKNOWNS},
                },
            },
        ],
        "properties": {
            "status": {"enum": ["answered", "abstained"]},
            "summary": {"type": "string", "minLength": 1, "maxLength": MAX_SUMMARY_LENGTH},
            "claims": {
                "type": "array",
                "maxItems": MAX_CLAIMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "citation_ids"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": MAX_CLAIM_LENGTH},
                        "citation_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                            "maxItems": MAX_CITATIONS_PER_CLAIM,
                            "uniqueItems": True,
                        },
                    },
                },
            },
            "unknowns": {
                "type": "array",
                "maxItems": MAX_UNKNOWNS,
                "items": {"type": "string", "minLength": 1, "maxLength": MAX_UNKNOWN_LENGTH},
            },
        },
    }


def answer_schema_document() -> str:
    return json.dumps(answer_schema(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AnswerClaim:
    text: str
    citation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "citation_ids": list(self.citation_ids)}


@dataclass(frozen=True)
class AnswerCitation:
    citation_id: str
    evidence_id: str
    snapshot_id: str
    commit_sha: str
    path: str
    symbol: str | None
    line_start: int
    line_end: int

    @classmethod
    def from_packed(cls, item: PackedEvidence) -> "AnswerCitation":
        return cls(
            citation_id=item.citation_id,
            evidence_id=item.evidence_id,
            snapshot_id=item.snapshot_id,
            commit_sha=item.commit_sha,
            path=item.path,
            symbol=item.symbol,
            line_start=item.line_start,
            line_end=item.line_end,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "evidence_id": self.evidence_id,
            "snapshot_id": self.snapshot_id,
            "commit_sha": self.commit_sha,
            "path": self.path,
            "symbol": self.symbol,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


@dataclass(frozen=True)
class StructuredAnswer:
    schema_version: str
    status: AnswerStatus
    question: str
    summary: str
    claims: tuple[AnswerClaim, ...]
    citations: tuple[AnswerCitation, ...]
    unknowns: tuple[str, ...]
    provider: str
    model: str
    trace_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "question": self.question,
            "summary": self.summary,
            "claims": [claim.to_dict() for claim in self.claims],
            "citations": [citation.to_dict() for citation in self.citations],
            "unknowns": list(self.unknowns),
            "provider": self.provider,
            "model": self.model,
            "trace_id": self.trace_id,
        }


def abstained_answer(
    question: str,
    reason: str,
    *,
    provider: str = "none",
    model: str = "none",
    trace_id: str | None = None,
) -> StructuredAnswer:
    if not question.strip() or not reason.strip():
        raise RepoLensError("Abstention question and reason must not be empty.")
    return StructuredAnswer(
        schema_version=ANSWER_SCHEMA_VERSION,
        status="abstained",
        question=question,
        summary=reason,
        claims=(),
        citations=(),
        unknowns=(reason,),
        provider=provider,
        model=model,
        trace_id=trace_id or uuid.uuid4().hex,
    )


def validate_provider_output(
    output: Mapping[str, Any],
    context: ContextPack,
    question: str,
    *,
    provider: str,
    model: str,
    trace_id: str | None = None,
) -> StructuredAnswer:
    """Validate a provider candidate and attach canonical evidence locators."""

    if not isinstance(output, Mapping):
        raise RepoLensError("Provider output must be a JSON object.")
    unknown_fields = set(output) - _ALLOWED_PROVIDER_FIELDS
    if unknown_fields:
        raise RepoLensError(f"Provider output has unsupported fields: {', '.join(sorted(unknown_fields))}.")
    missing = _ALLOWED_PROVIDER_FIELDS - set(output)
    if missing:
        raise RepoLensError(f"Provider output is missing fields: {', '.join(sorted(missing))}.")

    status = output["status"]
    summary = output["summary"]
    claims = output["claims"]
    unknowns = output["unknowns"]
    if status not in ("answered", "abstained"):
        raise RepoLensError("Provider answer status must be answered or abstained.")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_LENGTH:
        raise RepoLensError(
            f"Provider answer summary must be a non-empty string of at most {MAX_SUMMARY_LENGTH} characters."
        )
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        raise RepoLensError("Provider answer claims must be an array.")
    if not isinstance(unknowns, Sequence) or isinstance(unknowns, (str, bytes)):
        raise RepoLensError("Provider answer unknowns must be an array.")
    if len(claims) > MAX_CLAIMS:
        raise RepoLensError(f"Provider answer claims must contain at most {MAX_CLAIMS} items.")
    if len(unknowns) > MAX_UNKNOWNS:
        raise RepoLensError(f"Provider answer unknowns must contain at most {MAX_UNKNOWNS} items.")
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > MAX_UNKNOWN_LENGTH
        for item in unknowns
    ):
        raise RepoLensError(
            f"Provider answer unknowns must contain non-empty strings of at most {MAX_UNKNOWN_LENGTH} characters."
        )

    available = context.evidence_by_citation
    normalized_claims: list[AnswerClaim] = []
    cited_ids: list[str] = []
    for claim in claims:
        if not isinstance(claim, Mapping) or set(claim) != {"text", "citation_ids"}:
            raise RepoLensError("Each provider claim must contain only text and citation_ids.")
        text = claim["text"]
        citation_ids = claim["citation_ids"]
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CLAIM_LENGTH:
            raise RepoLensError(
                f"Provider claim text must be a non-empty string of at most {MAX_CLAIM_LENGTH} characters."
            )
        if not isinstance(citation_ids, Sequence) or isinstance(citation_ids, (str, bytes)):
            raise RepoLensError("Provider claim citation_ids must be an array.")
        if not citation_ids or any(not isinstance(item, str) or not item.strip() for item in citation_ids):
            raise RepoLensError("Every answered claim must include at least one citation ID.")
        if len(citation_ids) > MAX_CITATIONS_PER_CLAIM:
            raise RepoLensError(
                f"Each provider claim may cite at most {MAX_CITATIONS_PER_CLAIM} evidence IDs."
            )
        if len(set(citation_ids)) != len(citation_ids):
            raise RepoLensError("Citation IDs within a claim must be unique.")
        for citation_id in citation_ids:
            if citation_id not in available:
                raise RepoLensError(f"Provider cited unknown or un-packed evidence ID: {citation_id}.")
            if citation_id not in cited_ids:
                cited_ids.append(citation_id)
        normalized_claims.append(AnswerClaim(text=text, citation_ids=tuple(citation_ids)))

    if status == "answered":
        if not normalized_claims:
            raise RepoLensError("An answered response must contain at least one cited claim.")
        if not context.items:
            raise RepoLensError("An answered response is invalid without packed evidence.")
    else:
        if normalized_claims:
            raise RepoLensError("An abstained response must not contain claims.")
        if not unknowns:
            raise RepoLensError("An abstained response must explain what remains unknown.")
        if cited_ids:
            raise RepoLensError("An abstained response must not contain citations.")

    citations = tuple(AnswerCitation.from_packed(available[citation_id]) for citation_id in cited_ids)
    return StructuredAnswer(
        schema_version=ANSWER_SCHEMA_VERSION,
        status=status,
        question=question,
        summary=summary,
        claims=tuple(normalized_claims),
        citations=citations,
        unknowns=tuple(unknowns),
        provider=provider,
        model=model,
        trace_id=trace_id or uuid.uuid4().hex,
    )
