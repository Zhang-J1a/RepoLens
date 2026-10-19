import argparse
import json
import sqlite3
import sys

from repolens import __version__
from repolens.agent import AgentBudget, ControlledAgent
from repolens.config import data_directory
from repolens.domain import RepoLensError
from repolens.diagnostics import doctor
from repolens.evaluation import evaluate_dataset
from repolens.index import (
    KEYWORD_RETRIEVAL_POLICY,
    RETRIEVAL_POLICY,
    VECTOR_RETRIEVAL_POLICY,
    IndexStore,
)
from repolens.ingestion import ingest, ingest_or_reuse
from repolens.context import EvidenceContextPacker
from repolens.impact import analyze_impact, render_impact_markdown
from repolens.impact_evaluation import evaluate_impact_dataset
from repolens.git import GitRepository
from repolens.pipeline import QuestionAnswerPipeline
from repolens.provider import DeepSeekProvider, MockProvider
from repolens.webapp import serve_forever
from repolens.graph.schema import GRAPH_RETRIEVAL_POLICY
from repolens.graph.workflow import inspect_graph


def _bounded_int(label: str, minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} must be an integer.") from exc
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"{label} must be between {minimum} and {maximum}.")
        return parsed

    return parse


def _bounded_float(label: str, minimum: float, maximum: float):
    def parse(value: str) -> float:
        try:
            parsed = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} must be a number.") from exc
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"{label} must be between {minimum:g} and {maximum:g}.")
        return parsed

    return parse


def _storage_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", help="Index directory outside the target repository (or REPOLENS_DATA_DIR).")


def _answer_options(parser: argparse.ArgumentParser, *, ask_defaults: bool = False) -> None:
    parser.add_argument("--limit", type=_bounded_int("answer limit", 1, 100), default=8 if ask_defaults else 5)
    parser.add_argument(
        "--retrieval",
        choices=("keyword", "vector", "hybrid", "graph"),
        default="hybrid" if ask_defaults else "keyword",
        help="Retrieval path: FTS5 keyword, local vector, or weighted hybrid.",
    )
    parser.add_argument(
        "--context-tokens",
        type=_bounded_int("context token budget", 1, 100_000),
        default=1600 if ask_defaults else 1200,
    )
    parser.add_argument(
        "--output-tokens",
        type=_bounded_int("output token budget", 1, 8192),
        default=1024 if ask_defaults else 512,
    )
    parser.add_argument("--path-prefix", help="Literal repository-relative POSIX path prefix.")
    parser.add_argument("--provider", choices=("mock", "deepseek", "langchain"),
                        default="deepseek" if ask_defaults else "mock",
                        help="Model path: offline Mock, native DeepSeek client, or LangChain + DeepSeek.")
    parser.add_argument("--model", help="DeepSeek model override; defaults to DEEPSEEK_MODEL or deepseek-flash.")
    parser.add_argument(
        "--timeout",
        type=_bounded_float("DeepSeek timeout", 0.1, 600),
        default=None,
        help="DeepSeek request timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=_bounded_int("DeepSeek max retries", 0, 5),
        default=None,
        help="DeepSeek retry count for transient failures.",
    )
    parser.add_argument(
        "--max-follow-ups",
        type=_bounded_int("follow-up search budget", 0, 3),
        default=1 if ask_defaults else 0,
        help="Bounded additional retrieval rounds after insufficient evidence.",
    )


def _impact_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=("mock", "deepseek", "langchain"), default="mock")
    parser.add_argument("--model", help="DeepSeek model override; defaults to DEEPSEEK_MODEL or deepseek-flash.")
    parser.add_argument(
        "--context-tokens",
        type=_bounded_int("context token budget", 1, 100_000),
        default=2400,
    )
    parser.add_argument(
        "--output-tokens",
        type=_bounded_int("output token budget", 1, 8192),
        default=768,
    )
    parser.add_argument(
        "--timeout",
        type=_bounded_float("DeepSeek timeout", 0.1, 600),
        default=None,
        help="DeepSeek request timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=_bounded_int("DeepSeek max retries", 0, 5),
        default=None,
        help="DeepSeek retry count for transient failures.",
    )


def _provider(args):
    if args.provider == "mock":
        return MockProvider()
    if args.provider == "deepseek":
        return DeepSeekProvider.from_environment(
            model=args.model, timeout_seconds=args.timeout, max_retries=args.max_retries,
        )
    if args.provider == "langchain":
        try:
            from repolens.langchain_integration import LangChainDeepSeekProvider
        except ImportError:
            raise RepoLensError("LangChain support is optional; install the 'langchain' extra first.") from None

        return LangChainDeepSeekProvider.from_environment(
            model=args.model, timeout_seconds=args.timeout, max_retries=args.max_retries,
        )
    raise RepoLensError("provider must be mock, deepseek or langchain.")


def _run_answer(store, args, snapshot_id: str) -> dict:
    provider = _provider(args)
    pipeline = QuestionAnswerPipeline(
        store,
        snapshot_id,
        provider,
        context_packer=EvidenceContextPacker(args.context_tokens),
        max_output_tokens=args.output_tokens,
        max_follow_up_searches=args.max_follow_ups,
        retrieval_strategy=args.retrieval,
        retriever_factory=getattr(provider, "retriever_factory", None),
    )
    return pipeline.answer(args.question, limit=args.limit, path_prefix=args.path_prefix).to_dict()


def _print_chat_answer(result: dict, output_stream, turn: int) -> None:
    answer = result["answer"]
    print(f"\n[第 {turn} 轮] {answer['status']}", file=output_stream)
    print(answer["summary"], file=output_stream)
    for claim in answer["claims"]:
        citations = ", ".join(claim["citation_ids"])
        print(f"- {claim['text']} [{citations}]", file=output_stream)
    if answer["citations"]:
        print("引用:", file=output_stream)
        for citation in answer["citations"]:
            symbol = citation["symbol"] or "-"
            print(
                f"  [{citation['citation_id']}] {citation['path']}:{citation['line_start']}-{citation['line_end']} "
                f"({symbol})",
                file=output_stream,
            )
    if answer["unknowns"]:
        print("未知:", file=output_stream)
        for unknown in answer["unknowns"]:
            print(f"- {unknown}", file=output_stream)
    print(
        f"snapshot={result['snapshot_id']} trace={answer['trace_id']} "
        f"context_tokens={result['context']['tokens_used']}",
        file=output_stream,
    )


def _run_chat(args, directory, input_stream, output_stream) -> int:
    provider = _provider(args)
    ingestion = ingest_or_reuse(args.repository, directory, args.ref)
    history = []
    print(
        f"RepoLens chat | repository={ingestion['root']} | commit={ingestion['commit_sha']} | "
        f"index={ingestion['index_action']}",
        file=output_stream,
    )
    print("输入问题；`:help` 查看命令，`:quit` 退出。", file=output_stream)
    with IndexStore(directory) as store:
        pipeline = QuestionAnswerPipeline(
            store,
            ingestion["snapshot_id"],
            provider,
            context_packer=EvidenceContextPacker(args.context_tokens),
            max_output_tokens=args.output_tokens,
            max_follow_up_searches=args.max_follow_ups,
            retrieval_strategy=args.retrieval,
            retriever_factory=getattr(provider, "retriever_factory", None),
        )
        turn = 0
        while turn < args.max_turns:
            line = input_stream.readline()
            if line == "":
                break
            question = line.strip()
            if not question:
                continue
            if question in (":quit", ":exit", ":q"):
                break
            if question == ":help":
                print("命令：:help 查看帮助；:quit 或 :exit 退出。", file=output_stream)
                continue
            turn += 1
            try:
                result = pipeline.answer(
                    question,
                    limit=args.limit,
                    path_prefix=args.path_prefix,
                    history=history,
                ).to_dict()
            except RepoLensError as exc:
                print(f"本轮失败：{exc}", file=output_stream)
                continue
            _print_chat_answer(result, output_stream, turn)
            history.extend((
                {"role": "user", "content": question},
                {"role": "assistant", "content": result["answer"]["summary"][:2000]},
            ))
            history = history[-8:]
    print("会话结束。", file=output_stream)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repolens",
        description="Local Git code retrieval with snapshot-scoped evidence and offline evaluation.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("doctor", help="Check Python, Git, and SQLite/FTS5 without opening an index.")
    ingestion = commands.add_parser("ingest", help="Index committed Python/Markdown in a local Git snapshot.")
    ingestion.add_argument("repository", help="Local Git working tree or bare repository path.")
    ingestion.add_argument("--ref", default="HEAD", help="Locally available commit/ref (default: HEAD).")
    _storage_option(ingestion)

    search = commands.add_parser("search", help="Search one exact indexed snapshot with keyword, vector, or hybrid retrieval.")
    search.add_argument("query")
    search.add_argument("--snapshot", required=True)
    search.add_argument("--limit", type=_bounded_int("search limit", 1, 100), default=5)
    search.add_argument(
        "--retrieval", choices=("keyword", "vector", "hybrid", "graph"), default="hybrid",
        help="Retrieval path: FTS5 keyword, local vector, or weighted hybrid.",
    )
    search.add_argument("--path-prefix", help="Literal repository-relative POSIX path prefix.")
    _storage_option(search)

    history = commands.add_parser("history", help="Search commit history reachable from one indexed snapshot.")
    history.add_argument("query")
    history.add_argument("--snapshot", required=True)
    history.add_argument("--limit", type=_bounded_int("history limit", 1, 100), default=5)
    _storage_option(history)

    answer = commands.add_parser(
        "answer",
        help="Retrieve evidence and validate a structured answer from Mock, DeepSeek, or LangChain + DeepSeek.",
    )
    answer.add_argument("question")
    answer.add_argument("--snapshot", required=True)
    _answer_options(answer)
    _storage_option(answer)

    ask = commands.add_parser(
        "ask",
        help="Index a local repository and answer one question with DeepSeek.",
    )
    ask.add_argument("question")
    ask.add_argument("--repository", default=".", help="Local Git repository (default: current directory).")
    ask.add_argument("--ref", default="HEAD", help="Locally available commit/ref (default: HEAD).")
    _answer_options(ask, ask_defaults=True)
    _storage_option(ask)

    chat = commands.add_parser(
        "chat",
        help="Start a bounded multi-turn conversation about one local repository.",
    )
    chat.add_argument("--repository", default=".", help="Local Git repository (default: current directory).")
    chat.add_argument("--ref", default="HEAD", help="Locally available commit/ref (default: HEAD).")
    chat.add_argument("--max-turns", type=_bounded_int("chat turn limit", 1, 50), default=20)
    _answer_options(chat, ask_defaults=True)
    _storage_option(chat)

    agent = commands.add_parser("agent", help="Run a read-only agent with fixed tools, budgets and an audit trace.")
    agent.add_argument("question")
    agent.add_argument("--repository", default=".")
    agent.add_argument("--ref", default="HEAD", help="Task head commit/ref, pinned before tools run.")
    agent.add_argument("--base", help="Optional base commit/ref; preserve a V2 rule report on model failure.")
    _impact_options(agent)
    agent.set_defaults(max_retries=0)
    for flag, minimum, maximum, default in (
        ("max-steps", 1, 32, 8), ("max-model-calls", 1, 16, 6),
        ("max-total-tokens", 1, 200000, 32000), ("max-results-per-call", 1, 40, 8),
        ("max-total-results", 1, 500, 64),
    ):
        agent.add_argument("--" + flag, type=_bounded_int("Agent " + flag, minimum, maximum), default=default)
    agent.add_argument("--task-timeout", type=_bounded_float("Agent task timeout", 0.1, 600), default=120.0)
    _storage_option(agent)

    impact = commands.add_parser(
        "impact",
        help="Compare two local Git commits and produce a snapshot-pinned impact report.",
    )
    impact.add_argument("--repository", default=".", help="Local Git repository (default: current directory).")
    impact.add_argument("--base", required=True, help="Locally available base commit/ref.")
    impact.add_argument("--head", default="HEAD", help="Locally available head commit/ref (default: HEAD).")
    impact.add_argument("--format", choices=("json", "markdown"), default="json", help="Impact report output format.")
    impact.add_argument("--question", help="Optional question for the single structured model summary.")
    impact.add_argument("--with-graph", action="store_true", help="Attach a two-hop graph and graph review ordering.")
    _impact_options(impact)
    _storage_option(impact)

    analyze = commands.add_parser(
        "analyze",
        help="Analyze one commit against its first parent and produce a snapshot-pinned impact report.",
    )
    analyze.add_argument("kind", choices=("commit",), help="Analysis target kind.")
    analyze.add_argument("commit", help="Locally available full commit SHA or ref.")
    analyze.add_argument("--repository", default=".", help="Local Git repository (default: current directory).")
    analyze.add_argument("--format", choices=("json", "markdown"), default="json", help="Impact report output format.")
    analyze.add_argument("--question", help="Optional question for the single structured model summary.")
    analyze.add_argument("--with-graph", action="store_true", help="Attach a two-hop graph and graph review ordering.")
    _impact_options(analyze)
    _storage_option(analyze)

    impact_evaluation = commands.add_parser(
        "evaluate-impact",
        help="Evaluate snapshot-pinned impact reports against a reviewed JSON gold set.",
    )
    impact_evaluation.add_argument("dataset", help="UTF-8 JSON impact evaluation dataset.")
    impact_evaluation.add_argument("--repository", required=True, help="Local Git repository used by the cases.")
    _storage_option(impact_evaluation)

    graph = commands.add_parser("graph", help="Inspect a bounded snapshot-local code graph.")
    graph.add_argument("--repository", default=".")
    graph.add_argument("--ref", default="HEAD")
    graph.add_argument("--symbol")
    graph.add_argument("--path", help="Repository-relative path, optionally disambiguating a symbol.")
    graph.add_argument("--commit", action="store_true", help="Seed symbols in the selected commit's changed files.")
    graph.add_argument("--hops", type=_bounded_int("graph hops", 1, 2), default=2)
    graph.add_argument("--max-nodes", type=_bounded_int("graph nodes", 1, 500), default=100)
    graph.add_argument("--max-edges", type=_bounded_int("graph edges", 1, 2000), default=200)
    _storage_option(graph)

    serve = commands.add_parser(
        "serve",
        help="Start the local browser UI and loopback API.",
    )
    serve.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1")
    serve.add_argument("--port", type=_bounded_int("UI port", 0, 65535), default=0)
    serve.add_argument("--no-browser", action="store_true", help="Start the UI without opening a browser window.")
    _storage_option(serve)

    evidence = commands.add_parser("evidence", help="Resolve and check a stored evidence span.")
    evidence.add_argument("evidence_id")
    evidence.add_argument("--snapshot", required=True)
    _storage_option(evidence)

    snapshots = commands.add_parser("snapshots", help="List up to 100 indexed snapshots, newest first.")
    _storage_option(snapshots)

    evaluation = commands.add_parser("evaluate", help="Score retrieval against a validated JSONL evidence set.")
    evaluation.add_argument("dataset", help="UTF-8 JSONL dataset with expected evidence locators.")
    evaluation.add_argument("--snapshot", required=True, help="Exact indexed snapshot ID to evaluate.")
    evaluation.add_argument(
        "--limit",
        type=_bounded_int("evaluation limit", 10, 100),
        default=10,
        help="Maximum results per query (10-100).",
    )
    evaluation.add_argument(
        "--retrieval", choices=("keyword", "vector", "hybrid", "graph"), default="hybrid",
        help="Retrieval path to evaluate independently.",
    )
    _storage_option(evaluation)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    input_stream=None,
    output_stream=None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "doctor":
            result = doctor()
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["ok"] else 1
        directory = data_directory(args.data_dir)
        if args.command == "serve":
            serve_forever(
                args.host,
                args.port,
                default_data_dir=directory,
                open_browser=not args.no_browser,
            )
            return 0
        if args.command == "evaluate-impact":
            result = evaluate_impact_dataset(args.dataset, args.repository, directory)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        if args.command == "ingest":
            result = ingest(args.repository, directory, args.ref)
        elif args.command == "graph":
            result = inspect_graph(args.repository, directory, args.ref, symbol=args.symbol, path=args.path,
                                   commit=args.commit, hops=args.hops, max_nodes=args.max_nodes, max_edges=args.max_edges)
        elif args.command == "agent":
            budget = AgentBudget(
                max_steps=args.max_steps, max_model_calls=args.max_model_calls,
                max_total_tokens=args.max_total_tokens, max_results_per_call=args.max_results_per_call,
                max_total_results=args.max_total_results, context_tokens=args.context_tokens,
                output_tokens=args.output_tokens, timeout_seconds=args.task_timeout,
            )
            result = ControlledAgent(_provider(args), budget=budget).run(
                args.repository, directory, args.question, ref=args.ref, base_ref=args.base,
            )
        elif args.command == "ask":
            provider = _provider(args)
            ingestion = ingest_or_reuse(args.repository, directory, args.ref)
            with IndexStore(directory) as store:
                pipeline = QuestionAnswerPipeline(
                    store,
                    ingestion["snapshot_id"],
                    provider,
                    context_packer=EvidenceContextPacker(args.context_tokens),
                    max_output_tokens=args.output_tokens,
                    max_follow_up_searches=args.max_follow_ups,
                    retrieval_strategy=args.retrieval,
                    retriever_factory=getattr(provider, "retriever_factory", None),
                )
                result = pipeline.answer(
                    args.question,
                    limit=args.limit,
                    path_prefix=args.path_prefix,
                ).to_dict()
            result["workflow"] = {
                "repository": ingestion["root"],
                "ref": args.ref,
                "snapshot_id": ingestion["snapshot_id"],
                "commit_sha": ingestion["commit_sha"],
                "stats": ingestion["stats"],
                "ingest_elapsed_seconds": ingestion["elapsed_seconds"],
                "index_action": ingestion["index_action"],
            }
        elif args.command == "chat":
            return _run_chat(args, directory, input_stream, output_stream)
        elif args.command == "impact":
            result = analyze_impact(
                args.repository,
                directory,
                args.base,
                args.head,
                provider=_provider(args),
                context_tokens=args.context_tokens,
                output_tokens=args.output_tokens,
                question=args.question,
                with_graph=args.with_graph,
            )
        elif args.command == "analyze":
            git = GitRepository(args.repository)
            commit = git.commit(args.commit)
            if not commit.parents:
                raise RepoLensError("Cannot analyze the root commit because it has no first parent.")
            result = analyze_impact(
                args.repository,
                directory,
                commit.parents[0],
                commit.sha,
                provider=_provider(args),
                context_tokens=args.context_tokens,
                output_tokens=args.output_tokens,
                question=args.question,
                with_graph=args.with_graph,
            )
            result["workflow"] = {
                "repository": str(git.root),
                "commit_ref": args.commit,
                "base_ref": commit.parents[0],
                "head_ref": commit.sha,
            }
        else:
            with IndexStore(directory) as store:
                if args.command == "snapshots":
                    result = {"snapshots": store.snapshots()}
                elif args.command == "search":
                    retrieval_policy = {
                        "keyword": KEYWORD_RETRIEVAL_POLICY,
                        "vector": VECTOR_RETRIEVAL_POLICY,
                        "hybrid": RETRIEVAL_POLICY,
                        "graph": GRAPH_RETRIEVAL_POLICY,
                    }[args.retrieval]
                    result = {
                        "query": args.query, "snapshot_id": args.snapshot, "retrieval": retrieval_policy,
                        "strategy": args.retrieval,
                        "candidate_policy": "fixed-100",
                        "results": getattr(store, {
                            "keyword": "search", "vector": "search_vector", "hybrid": "search_hybrid", "graph": "search_graph",
                        }[args.retrieval])(args.query, args.snapshot, limit=args.limit, path_prefix=args.path_prefix),
                    }
                elif args.command == "history":
                    result = {
                        "query": args.query,
                        "snapshot_id": args.snapshot,
                        "retrieval": "history-fts5-bm25-v1",
                        "results": store.search_history(args.query, args.snapshot, limit=args.limit),
                    }
                elif args.command == "answer":
                    result = _run_answer(store, args, args.snapshot)
                elif args.command == "evaluate":
                    result = evaluate_dataset(
                        args.dataset, store, args.snapshot, limit=args.limit, strategy=args.retrieval,
                    )
                else:
                    result = store.evidence(args.evidence_id, args.snapshot)
        if args.command in ("impact", "analyze") and args.format == "markdown":
            print(render_impact_markdown(result), end="")
        else:
            print(json.dumps(result, ensure_ascii=True, indent=2))
    except RepoLensError as exc:
        print(f"repolens: {args.command} failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error):
        print(f"repolens: {args.command} failed: check index path, permissions, and SQLite/FTS5 availability.", file=sys.stderr)
        return 1
    return 0
