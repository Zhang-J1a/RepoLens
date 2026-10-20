"""Run the offline Mock benchmark preparation; no real provider is available here."""

import argparse
import json
from pathlib import Path

from repolens.benchmark import STRATEGIES, run_benchmark
from repolens.domain import RepoLensError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--max-calls", type=int, default=32)
    parser.add_argument("--max-planned-tokens", type=int, default=200000)
    args = parser.parse_args(argv)
    try:
        report = run_benchmark(args.dataset, args.index, args.snapshot, args.output_dir,
                               strategies=args.strategies, max_calls=args.max_calls,
                               max_planned_tokens=args.max_planned_tokens)
    except (RepoLensError, OSError):
        print(json.dumps({"error_code": "benchmark_failed", "hint": "Check inputs, frozen policy and output permissions."}))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report["failed"] or report["uncertain"] or report["remaining"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
