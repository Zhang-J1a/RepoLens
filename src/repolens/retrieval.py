"""Deterministic lexical candidate reranking for repository evidence."""

import re


IDENTIFIER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_.]*")
RERANK_COVERAGE_WEIGHT = 4.0
RERANK_SYMBOL_ROOT_WEIGHT = 3.0

# A small, explicit vocabulary keeps multilingual retrieval deterministic and
# auditable. These are retrieval hints, not translations or model claims.
MULTILINGUAL_QUERY_EXPANSIONS = {
    "入口": ("main", "entry", "entrypoint", "start"),
    "启动": ("main", "start", "run", "launch"),
    "运行": ("run", "execute", "main"),
    "读写": ("read", "write", "load", "save", "io"),
    "读取": ("read", "load", "get", "parse"),
    "写入": ("write", "save", "dump", "export"),
    "保存": ("save", "write", "store"),
    "加载": ("load", "read", "parse"),
    "书籍": ("book", "books"),
    "文件": ("file", "path"),
    "数据": ("data", "result", "results"),
    "项目": ("project", "repository"),
    "函数": ("function", "method"),
    "配置": ("config", "configuration", "settings"),
    "请求": ("request", "route", "endpoint"),
    "异常": ("error", "exception", "handle"),
    "处理": ("handle", "process"),
    "测试": ("test", "tests"),
    "文档": ("doc", "docs", "documentation"),
}


def identifier_terms(query: str) -> tuple[str, ...]:
    """Return ASCII code identifiers while preserving underscores and dots."""
    return tuple(dict.fromkeys(
        term.lower()
        for term in IDENTIFIER_PATTERN.findall(query)
        if any(char.isalpha() for char in term)
    ))


def query_expansion_terms(query: str) -> tuple[str, ...]:
    """Return bounded English/code hints for common Chinese code questions."""

    if not isinstance(query, str):
        return ()
    terms = []
    for marker, expansions in MULTILINGUAL_QUERY_EXPANSIONS.items():
        if marker in query:
            terms.extend(expansions)
    return tuple(dict.fromkeys(terms))


def rerank_candidates(candidates, query: str, limit: int):
    """Rerank FTS candidates using query-term coverage and symbol hierarchy.

    BM25 remains the primary candidate generator. Coverage is deliberately
    lexical: it rewards a candidate containing more query identifiers, while a
    class or namespace prefix gives a smaller structural signal. No repository
    or benchmark-specific names are used here.
    """
    terms = tuple(term for term in (*identifier_terms(query), *query_expansion_terms(query)) if len(term) >= 3)
    ranked = []
    for ordinal, candidate in enumerate(candidates):
        symbol = (candidate["symbol"] or "").lower()
        path = candidate["path"].lower()
        text = candidate["text"].lower()
        coverage = sum(term in symbol or term in path or term in text for term in terms)
        symbol_root = sum(symbol == term or symbol.startswith(term + ".") for term in terms)
        rank_score = (
            candidate["bm25_score"]
            - RERANK_COVERAGE_WEIGHT * coverage
            - RERANK_SYMBOL_ROOT_WEIGHT * symbol_root
        )
        ranked.append((rank_score, candidate["bm25_score"], ordinal, candidate))
    ranked.sort(key=lambda item: (item[0], item[1], item[3]["path"], item[3]["line_start"], item[3]["id"]))
    return [item[3] for item in ranked[:limit]]
