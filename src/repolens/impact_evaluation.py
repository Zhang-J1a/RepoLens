"""Offline structural evaluation for snapshot-pinned impact reports."""

from collections.abc import Mapping
from pathlib import Path
import json
import math
import time

from repolens.domain import RepoLensError
from repolens.git import safe_repository_path
from repolens.impact import analyze_impact
from repolens.ingestion import ingest_or_reuse
from repolens.index import IndexStore


IMPACT_EVAL_SCHEMA_VERSION = "repolens.impact-eval.v1"
RISK_SEVERITIES = {"low", "medium", "high", "blocking"}


def _read_dataset(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepoLensError("Impact evaluation dataset must be UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != IMPACT_EVAL_SCHEMA_VERSION:
        raise RepoLensError("Impact evaluation dataset has an unsupported schema version.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RepoLensError("Impact evaluation dataset must contain non-empty cases.")
    return payload, __import__("hashlib").sha256(raw).hexdigest()


def _validate_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) not in (40, 64) or any(char not in "0123456789abcdef" for char in value):
        raise RepoLensError(f"Impact evaluation {label} must be a full lowercase commit SHA.")
    return value


def _validate_case(case: object, number: int) -> dict:
    if not isinstance(case, dict):
        raise RepoLensError(f"Impact evaluation case {number} must be an object.")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise RepoLensError(f"Impact evaluation case {number} needs a non-empty id.")
    normalized = {
        "id": case_id,
        "base_sha": _validate_sha(case.get("base_sha"), f"case {case_id} base_sha"),
        "head_sha": _validate_sha(case.get("head_sha"), f"case {case_id} head_sha"),
    }
    for key in ("expected_changed_files", "expected_related_tests", "expected_related_docs", "expected_risk_severities"):
        value = case.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise RepoLensError(f"Impact evaluation case {case_id} field {key} must be a list of text.")
        if key != "expected_risk_severities" and any(not safe_repository_path(item) for item in value):
            raise RepoLensError(f"Impact evaluation case {case_id} contains an unsafe path in {key}.")
        if key == "expected_risk_severities" and any(item not in RISK_SEVERITIES for item in value):
            raise RepoLensError(f"Impact evaluation case {case_id} contains an unsupported risk severity.")
        normalized[key] = list(dict.fromkeys(value))
    symbols = case.get("expected_changed_symbols", [])
    if not isinstance(symbols, list):
        raise RepoLensError(f"Impact evaluation case {case_id} expected_changed_symbols must be a list.")
    normalized_symbols = []
    for symbol in symbols:
        if not isinstance(symbol, dict) or not safe_repository_path(symbol.get("path", "")):
            raise RepoLensError(f"Impact evaluation case {case_id} has an invalid changed symbol path.")
        if not isinstance(symbol.get("name"), str) or not symbol["name"].strip():
            raise RepoLensError(f"Impact evaluation case {case_id} has an invalid changed symbol name.")
        if symbol.get("change") not in {"added", "removed", "modified"}:
            raise RepoLensError(f"Impact evaluation case {case_id} has an invalid changed symbol change type.")
        normalized_symbols.append({"path": symbol["path"], "name": symbol["name"], "change": symbol["change"]})
    normalized["expected_changed_symbols"] = normalized_symbols
    return normalized


def _f1(expected: set, actual: set) -> dict:
    true_positive = len(expected & actual)
    precision = true_positive / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else (1.0 if not actual else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected": len(expected),
        "actual": len(actual),
        "true_positive": true_positive,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _metric_sets(report: Mapping[str, object]) -> dict[str, set]:
    changed_files = {
        str(item["path"])
        for item in report.get("changed_files", [])
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    changed_symbols = {
        (str(item["path"]), str(symbol["name"]), str(symbol["change"]))
        for item in report.get("changed_files", [])
        if isinstance(item, Mapping)
        for symbol in item.get("symbols", [])
        if isinstance(symbol, Mapping)
    }
    related_tests = {
        str(item["path"])
        for item in report.get("related_tests", [])
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    related_docs = {
        str(item["path"])
        for item in report.get("related_docs", [])
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    risk_severities = {
        str(item["severity"])
        for item in report.get("risks", [])
        if isinstance(item, Mapping) and isinstance(item.get("severity"), str)
    }
    return {
        "changed_files": changed_files,
        "changed_symbols": changed_symbols,
        "related_tests": related_tests,
        "related_docs": related_docs,
        "risk_severities": risk_severities,
    }


def _evidence_quality(report: Mapping[str, object], store: IndexStore) -> dict:
    evidence_rows = report.get("evidence", [])
    evidence_keys = set()
    valid_evidence = 0
    errors = []
    for item in evidence_rows:
        if not isinstance(item, Mapping):
            errors.append("evidence entry is not an object")
            continue
        evidence_id = item.get("evidence_id")
        snapshot_id = item.get("snapshot_id")
        if not isinstance(evidence_id, str) or not isinstance(snapshot_id, str):
            errors.append("evidence entry lacks evidence_id or snapshot_id")
            continue
        evidence_keys.add((snapshot_id, evidence_id))
        try:
            canonical = store.evidence(evidence_id, snapshot_id)
            for key in ("path", "line_start", "line_end", "commit_sha"):
                if item.get(key) != canonical.get(key):
                    raise RepoLensError(f"evidence field {key} does not match canonical storage")
            valid_evidence += 1
        except RepoLensError as exc:
            errors.append(str(exc))

    references = []
    for change in report.get("changed_files", []):
        for symbol in change.get("symbols", []) if isinstance(change, Mapping) else []:
            if symbol.get("evidence_id"):
                references.append((symbol.get("evidence_snapshot_id"), symbol.get("evidence_id")))
    for key in ("related_callers", "related_callees"):
        for relation in report.get(key, []):
            references.append((relation.get("snapshot_id"), relation.get("evidence_id")))
    for risk in report.get("risks", []):
        references.extend((None, evidence_id) for evidence_id in risk.get("evidence_ids", []))
    for suggestion in report.get("suggested_tests", []):
        references.extend((None, evidence_id) for evidence_id in suggestion.get("evidence_ids", []))
    bound_references = 0
    for snapshot_id, evidence_id in references:
        if snapshot_id is None:
            matches = [key for key in evidence_keys if key[1] == evidence_id]
            if matches:
                bound_references += 1
        elif (snapshot_id, evidence_id) in evidence_keys:
            bound_references += 1
    return {
        "evidence_count": len(evidence_rows),
        "valid_evidence_count": valid_evidence,
        "evidence_valid_rate": valid_evidence / len(evidence_rows) if evidence_rows else 0.0,
        "reference_count": len(references),
        "bound_reference_count": bound_references,
        "reference_binding_rate": bound_references / len(references) if references else 1.0,
        "errors": errors[:20],
    }


def evaluate_impact_dataset(
    dataset_path: str | Path,
    repository: str | Path,
    directory: Path,
) -> dict:
    """Run deterministic impact reports against a small, reviewed gold set."""

    payload, dataset_sha256 = _read_dataset(Path(dataset_path))
    cases = [_validate_case(case, index) for index, case in enumerate(payload["cases"], 1)]
    if len({case["id"] for case in cases}) != len(cases):
        raise RepoLensError("Impact evaluation case IDs must be unique.")
    case_results = []
    started_at = time.perf_counter()
    with IndexStore(directory, writable=True) as migration_store:
        migration_store.connection.commit()
    for case in cases:
        case_started = time.perf_counter()
        try:
            base = ingest_or_reuse(repository, directory, case["base_sha"])
            head = ingest_or_reuse(repository, directory, case["head_sha"])
            with IndexStore(directory) as store:
                report = analyze_impact(
                    str(repository), directory, case["base_sha"], case["head_sha"], provider=None,
                )
                actual = _metric_sets(report)
                expected = {
                    "changed_files": set(case["expected_changed_files"]),
                    "changed_symbols": {
                        (item["path"], item["name"], item["change"])
                        for item in case["expected_changed_symbols"]
                    },
                    "related_tests": set(case["expected_related_tests"]),
                    "related_docs": set(case["expected_related_docs"]),
                    "risk_severities": set(case["expected_risk_severities"]),
                }
                metrics = {key: _f1(expected[key], actual[key]) for key in expected}
                quality = _evidence_quality(report, store)
                schema_valid = report.get("schema_version") == "repolens.impact.v2"
                snapshot_bound = (
                    report.get("base", {}).get("snapshot_id") == base["snapshot_id"]
                    and report.get("head", {}).get("snapshot_id") == head["snapshot_id"]
                    and all(
                        item.get("snapshot_id") in {base["snapshot_id"], head["snapshot_id"]}
                        for item in report.get("evidence", [])
                    )
                )
                case_results.append({
                    "id": case["id"],
                    "status": "ok",
                    "report_status": report.get("status"),
                    "schema_valid": schema_valid,
                    "snapshot_bound": snapshot_bound,
                    "metrics": metrics,
                    "evidence_quality": quality,
                    "latency_ms": (time.perf_counter() - case_started) * 1000,
                })
        except (OSError, RepoLensError) as exc:
            case_results.append({
                "id": case["id"],
                "status": "error",
                "error": str(exc),
                "latency_ms": (time.perf_counter() - case_started) * 1000,
            })

    ok_cases = [case for case in case_results if case["status"] == "ok"]
    metric_names = ("changed_files", "changed_symbols", "related_tests", "related_docs", "risk_severities")
    aggregate = {}
    for metric_name in metric_names:
        aggregate[metric_name] = {
            key: sum(case["metrics"][metric_name][key] for case in ok_cases) / len(ok_cases)
            for key in ("precision", "recall", "f1")
        } if ok_cases else {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    return {
        "schema_version": IMPACT_EVAL_SCHEMA_VERSION,
        "run": {
            "dataset": Path(dataset_path).name,
            "dataset_sha256": dataset_sha256,
            "repository": str(repository),
            "case_count": len(cases),
            "successful_cases": len(ok_cases),
            "error_cases": len(case_results) - len(ok_cases),
            "duration_ms": (time.perf_counter() - started_at) * 1000,
        },
        "metrics": aggregate,
        "quality": {
            "schema_valid_rate": sum(case.get("schema_valid", False) for case in ok_cases) / len(ok_cases) if ok_cases else 0.0,
            "snapshot_binding_rate": sum(case.get("snapshot_bound", False) for case in ok_cases) / len(ok_cases) if ok_cases else 0.0,
            "evidence_valid_rate": sum(case["evidence_quality"]["evidence_valid_rate"] for case in ok_cases) / len(ok_cases) if ok_cases else 0.0,
            "reference_binding_rate": sum(case["evidence_quality"]["reference_binding_rate"] for case in ok_cases) / len(ok_cases) if ok_cases else 0.0,
        },
        "cases": case_results,
    }
