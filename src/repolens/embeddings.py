"""Small, replaceable embedding contracts and the offline vector baseline.

The local implementation is intentionally a TF-IDF sparse vectorizer. It is a
deterministic retrieval baseline, not a semantic model and not a substitute
for an external embedding service. Keeping the provider behind this interface
lets a later provider use the same SQLite/vector retrieval contract.
"""

from collections import Counter
from math import log, sqrt
import re
from typing import Iterable, Mapping, Protocol

from repolens.domain import RepoLensError


SparseVector = dict[str, float]
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


class EmbeddingProvider(Protocol):
    """Minimal provider contract used by the index, independent of a vendor."""

    provider_id: str

    def fit(self, documents: Iterable[str]) -> None:
        """Fit any corpus-dependent state needed to encode documents."""

    def embed(self, text: str) -> SparseVector:
        """Return one normalized sparse vector for a text string."""

    def model_json(self) -> dict:
        """Return a JSON-serializable model description for persistence."""


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize code, prose, identifiers, and individual CJK characters.

    Keeping identifier components makes ``load_books`` searchable from a
    natural-language query containing ``load`` or ``books`` without claiming
    that this baseline understands code semantics.
    """

    if not isinstance(text, str):
        raise RepoLensError("Embedding text must be a string.")
    tokens: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text.lower()):
        if _CJK_PATTERN.fullmatch(raw):
            tokens.append(raw)
            continue
        tokens.append(raw)
        tokens.extend(part for part in re.split(r"[_.]", raw) if part and part != raw)
    return tuple(tokens)


class LocalTfidfEmbeddingProvider:
    """Deterministic, dependency-free sparse TF-IDF embedding provider."""

    provider_id = "local-tfidf-v1"

    def __init__(self, *, max_features: int = 20_000):
        if not 128 <= max_features <= 100_000:
            raise RepoLensError("TF-IDF max_features must be between 128 and 100000.")
        self.max_features = max_features
        self.document_count = 0
        self._idf: dict[str, float] = {}

    @property
    def fitted(self) -> bool:
        return bool(self._idf) and self.document_count > 0

    def fit(self, documents: Iterable[str]) -> None:
        document_frequency: Counter[str] = Counter()
        count = 0
        for document in documents:
            terms = set(tokenize(document))
            if not terms:
                continue
            count += 1
            document_frequency.update(terms)
        if count == 0:
            # An empty snapshot is valid, but cannot answer vector queries.
            self.document_count = 0
            self._idf = {}
            return
        ranked_terms = sorted(document_frequency.items(), key=lambda item: (-item[1], item[0]))
        selected = sorted(term for term, _ in ranked_terms[: self.max_features])
        self.document_count = count
        self._idf = {
            term: log((1.0 + count) / (1.0 + document_frequency[term])) + 1.0
            for term in selected
        }

    def embed(self, text: str) -> SparseVector:
        if not self.fitted:
            raise RepoLensError("Embedding provider is not fitted to an index snapshot.")
        counts = Counter(token for token in tokenize(text) if token in self._idf)
        weighted = {token: count * self._idf[token] for token, count in counts.items()}
        norm = sqrt(sum(value * value for value in weighted.values()))
        if norm == 0.0:
            return {}
        return {token: value / norm for token, value in weighted.items()}

    def model_json(self) -> dict:
        if not self.fitted:
            raise RepoLensError("Cannot persist an unfitted embedding provider.")
        return {
            "provider_id": self.provider_id,
            "version": 1,
            "max_features": self.max_features,
            "document_count": self.document_count,
            "idf": self._idf,
        }

    @classmethod
    def from_model_json(cls, model: Mapping[str, object]) -> "LocalTfidfEmbeddingProvider":
        if model.get("provider_id") != cls.provider_id or model.get("version") != 1:
            raise RepoLensError("Unsupported persisted embedding model.")
        max_features = model.get("max_features")
        document_count = model.get("document_count")
        raw_idf = model.get("idf")
        if type(max_features) is not int or type(document_count) is not int or not isinstance(raw_idf, dict):
            raise RepoLensError("Persisted embedding model is malformed.")
        provider = cls(max_features=max_features)
        provider.document_count = document_count
        provider._idf = {
            str(term): float(value)
            for term, value in raw_idf.items()
            if isinstance(term, str) and isinstance(value, (int, float)) and value > 0
        }
        if document_count < 1 or not provider._idf:
            raise RepoLensError("Persisted embedding model has no usable vocabulary.")
        return provider


def cosine_similarity(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Compute cosine similarity for arbitrary sparse vectors."""

    if not left or not right:
        return 0.0
    smaller, larger = (left, right) if len(left) <= len(right) else (right, left)
    dot = sum(value * larger.get(term, 0.0) for term, value in smaller.items())
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def load_provider(model: Mapping[str, object]) -> EmbeddingProvider:
    """Rehydrate a persisted provider without importing vendor SDKs."""

    provider_id = model.get("provider_id")
    if provider_id == LocalTfidfEmbeddingProvider.provider_id:
        return LocalTfidfEmbeddingProvider.from_model_json(model)
    raise RepoLensError(f"Unsupported embedding provider {provider_id!r}.")
