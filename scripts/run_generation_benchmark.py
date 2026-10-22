"""Run a bounded offline or explicitly authorized model generation benchmark."""

import argparse
import json
from pathlib import Path

from repolens.benchmark import STRATEGIES, run_benchmark
from repolens.domain import RepoLensError
from repolens.provider import DeepSeekProvider, MockProvider


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--provider", choices=("mock", "deepseek", "langchain"), default="mock")
    parser.add_argument("--model")
    parser.add_argument("--context-tokens", type=int, default=2400)
    parser.add_argument("--output-tokens", type=int, default=768)
    parser.add_argument("--max-calls", type=int, default=32)
    parser.add_argument("--max-planned-tokens", type=int, default=200000)
    args = parser.parse_args(argv)
    try:
        if args.provider == "mock":
            provider = MockProvider()
        elif args.provider == "deepseek":
            provider = DeepSeekProvider.from_environment(model=args.model)
        else:
            from repolens.langchain_integration import LangChainDeepSeekProvider
            provider = LangChainDeepSeekProvider.from_environment(model=args.model)
        report = run_benchmark(args.dataset, args.index, args.snapshot, args.output_dir,
                               strategies=args.strategies, max_calls=args.max_calls,
                               max_planned_tokens=args.max_planned_tokens,
                               context_tokens=args.context_tokens, output_tokens=args.output_tokens,
                               provider=provider, export_responses=args.provider != "mock")
    except (RepoLensError, OSError):
        print(json.dumps({"error_code": "benchmark_failed", "hint": "Check inputs, frozen policy and output permissions."}))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report["failed"] or report["uncertain"] or report["remaining"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
