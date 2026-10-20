"""Check declared M4 inputs without opening Git repositories or running queries."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from repolens.domain import RepoLensError
from repolens.evaluation import _read_dataset
from repolens.git import safe_repository_path


SCHEMA = "repolens.m4-input.v1"
CATEGORIES = (
    "identifier", "english_natural_language", "chinese_no_identifier",
    "cross_file", "history", "abstention",
)
FULL_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
EXCLUDED = {
    "all-in-rag", "agentguide", "flask", "repolens", "taskboard", "taskboard-v0",
    "book manager v1", "book-manager-v1",
}


def _text(record: dict, key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RepoLensError(f"M4 input requires a nonempty {key} string.")
    return value


def _sha(value: object) -> bool:
    return isinstance(value, str) and FULL_SHA.fullmatch(value) is not None


def _locators(case: dict) -> list[dict]:
    locators = case.get("expected_evidence")
    if not isinstance(locators, list):
        raise RepoLensError("M4 expected_evidence must be a list.")
    seen = set()
    for locator in locators:
        if not isinstance(locator, dict):
            raise RepoLensError("M4 evidence locator must be an object.")
        path = locator.get("path")
        start, end, symbol = (locator.get(key) for key in ("line_start", "line_end", "symbol"))
        if not isinstance(path, str) or not safe_repository_path(path):
            raise RepoLensError("M4 evidence requires a safe repository-relative POSIX path.")
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            raise RepoLensError("M4 evidence requires a 1-based inclusive line range.")
        if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
            raise RepoLensError("M4 evidence symbol must be null or a nonempty string.")
        identity = (path, start, end, symbol)
        if identity in seen:
            raise RepoLensError("M4 case repeats an evidence locator.")
        seen.add(identity)
    return locators


def validate_plan(path: str | Path) -> dict:
    """Validate declarations and dataset shape; this is not a benchmark gate."""
    plan_path = Path(path)
    try:
        raw = plan_path.read_bytes()
        plan = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RepoLensError("Could not read the M4 input plan as UTF-8 JSON.") from exc
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA:
        raise RepoLensError(f"M4 input schema_version must be {SCHEMA}.")
    _text(plan, "annotator")
    repositories = plan.get("repositories")
    if not isinstance(repositories, list) or not 3 <= len(repositories) <= 5:
        raise RepoLensError("M4 requires 3 to 5 declared external Python repositories.")

    repo_ids, local_paths, case_ids = set(), set(), set()
    summaries = []
    for repository in repositories:
        if not isinstance(repository, dict):
            raise RepoLensError("M4 repository entry must be an object.")
        repo_id = _text(repository, "id")
        local_path = _text(repository, "local_path")
        names = {part.casefold() for part in repo_id.replace("\\", "/").split("/")}
        names.add(local_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].casefold())
        if names & EXCLUDED:
            raise RepoLensError("Learning references and existing development corpora are excluded from M4.")
        if repo_id in repo_ids or local_path in local_paths:
            raise RepoLensError("M4 repository IDs and declared local paths must be unique.")
        repo_ids.add(repo_id)
        local_paths.add(local_path)
        if repository.get("language") != "python" or repository.get("external_blind") is not True:
            raise RepoLensError("M4 requires Python repositories declared external_blind=true.")
        if not _sha(repository.get("commit_sha")):
            raise RepoLensError("M4 repository requires a full lowercase commit SHA.")
        for key in ("license", "authorization_note"):
            _text(repository, key)
        if type(repository.get("publish_metadata")) is not bool:
            raise RepoLensError("M4 publish_metadata must be an explicit boolean.")
        dataset_name = _text(repository, "dataset")
        dataset_path = Path(dataset_name)
        if not dataset_path.is_absolute():
            dataset_path = plan_path.parent / dataset_path
        cases, dataset_hash = _read_dataset(dataset_path)
        if len(cases) < 15:
            raise RepoLensError("M4 requires at least 15 cases per repository.")
        counts = Counter()
        locator_count = commit_count = 0
        for case in cases:
            case_id = _text(case, "id")
            if case_id in case_ids:
                raise RepoLensError("M4 case IDs must be globally unique.")
            case_ids.add(case_id)
            if case.get("repo") != repo_id or case.get("commit_sha") != repository["commit_sha"]:
                raise RepoLensError("M4 case repo/commit must match its repository declaration.")
            query = _text(case, "query")
            if len(query) > 4096:
                raise RepoLensError("M4 query exceeds the existing 4096-character query limit.")
            _text(case, "review_notes")
            category = case.get("category")
            if not isinstance(category, str) or category not in CATEGORIES:
                raise RepoLensError("M4 case has an unsupported category.")
            counts[category] += 1
            expected = "abstain" if category == "abstention" else "answer"
            if case.get("expected_behavior") != expected:
                raise RepoLensError("M4 expected_behavior must agree with the category.")
            locators = _locators(case)
            commits = case.get("expected_commits", [])
            if not isinstance(commits, list) or any(not _sha(sha) for sha in commits):
                raise RepoLensError("M4 expected_commits must contain full lowercase SHAs.")
            if len(set(commits)) != len(commits):
                raise RepoLensError("M4 case repeats an expected commit.")
            if category == "abstention":
                if locators or commits:
                    raise RepoLensError("M4 abstention cases must not fabricate gold evidence.")
            elif category == "history":
                if not commits:
                    raise RepoLensError("M4 history cases require expected_commits.")
            elif not locators or commits:
                raise RepoLensError("M4 source cases require locators and no history-only gold.")
            if category == "cross_file" and len({item["path"] for item in locators}) < 2:
                raise RepoLensError("M4 cross_file cases require evidence from at least two files.")
            locator_count += len(locators)
            commit_count += len(commits)
        if set(counts) != set(CATEGORIES):
            raise RepoLensError("M4 requires all six categories in every repository dataset.")
        summaries.append({
            "repository": repo_id, "commit_sha": repository["commit_sha"],
            "dataset_sha256": dataset_hash, "case_count": len(cases),
            "locator_count": locator_count, "expected_commit_count": commit_count,
            "by_category": dict(sorted(counts.items())),
            "publish_metadata": repository["publish_metadata"],
        })
    return {
        "schema_version": "repolens.m4-preflight.v1",
        "status": "input_shape_validated",
        "plan_sha256": hashlib.sha256(raw).hexdigest(),
        "case_count": len(case_ids), "repositories": summaries,
        "benchmark_ready": False,
        "remaining_checks": [
            "Confirm authorization, distinct canonical Git roots, Python content and corpus diversity.",
            "Review licenses, blind-test eligibility and permission to publish metadata.",
            "Resolve commits locally and validate source locators and history reachability.",
            "Review category semantics and gold sufficiency without retrieval results.",
            "Freeze datasets, implementation/policy hashes, annotator and UTC timestamp before retrieval.",
            "Implement and validate M4 metric/report runner and full-context availability protocol.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args(argv)
    try:
        report = validate_plan(args.plan)
    except RepoLensError as exc:
        print(json.dumps({"status": "input_rejected", "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
