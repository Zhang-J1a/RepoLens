import contextlib
import io
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, sentinel

from repolens.cli import _provider, _run_chat, build_parser, main
from repolens.diagnostics import doctor
from repolens.domain import RepoLensError


class CliTests(unittest.TestCase):
    def test_ask_and_chat_use_the_selected_providers_retriever(self):
        provider = SimpleNamespace(retriever_factory=sentinel.retriever)
        ingestion = {"root": "unit-repository", "commit_sha": "a" * 40, "index_action": "reused",
                     "snapshot_id": "snapshot-unit", "stats": {}, "elapsed_seconds": 0.0}
        pipeline = Mock()
        pipeline.answer.return_value.to_dict.return_value = {}
        with patch("repolens.cli._provider", return_value=provider), \
                patch("repolens.cli.ingest_or_reuse", return_value=ingestion), \
                patch("repolens.cli.IndexStore"), \
                patch("repolens.cli.data_directory", return_value=sentinel.directory), \
                patch("repolens.cli.QuestionAnswerPipeline", return_value=pipeline) as constructor:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ask", "question", "--provider", "langchain"]), 0)
            self.assertIs(constructor.call_args.kwargs["retriever_factory"], sentinel.retriever)
            constructor.reset_mock()
            args = build_parser().parse_args(["chat", "--provider", "langchain"])
            self.assertEqual(_run_chat(args, sentinel.directory, io.StringIO(":quit\n"), io.StringIO()), 0)
            self.assertIs(constructor.call_args.kwargs["retriever_factory"], sentinel.retriever)

    def test_optional_langchain_dependency_has_an_actionable_error(self):
        args = build_parser().parse_args(["ask", "question", "--provider", "langchain"])
        with patch.dict(sys.modules, {"repolens.langchain_integration": None}):
            with self.assertRaisesRegex(RepoLensError, "install the 'langchain' extra"):
                _provider(args)

    def test_version_option_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                build_parser().parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("repolens 4.1.0", output.getvalue())

    def test_ask_defaults_to_current_repository_and_deepseek(self):
        args = build_parser().parse_args(["ask", "question"])
        self.assertEqual(args.repository, ".")
        self.assertEqual(args.ref, "HEAD")
        self.assertEqual(args.provider, "deepseek")
        self.assertEqual(args.context_tokens, 1600)
        self.assertEqual(args.output_tokens, 1024)
        self.assertEqual(args.max_follow_ups, 1)

    def test_chat_defaults_and_turn_limit(self):
        args = build_parser().parse_args(["chat"])
        self.assertEqual(args.repository, ".")
        self.assertEqual(args.provider, "deepseek")
        self.assertEqual(args.max_turns, 20)
        self.assertEqual(args.output_tokens, 1024)
        self.assertEqual(args.max_follow_ups, 1)

    def test_answer_rejects_out_of_range_generation_options(self):
        parser = build_parser()
        for option, value in (("--context-tokens", "0"), ("--output-tokens", "9000"), ("--max-retries", "6")):
            with self.subTest(option=option):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args([
                        "answer", "question", "--snapshot", "snapshot-1", option, value,
                    ])
                self.assertEqual(raised.exception.code, 2)

    def test_doctor_missing_git_reports_actionable_failure(self):
        with patch("repolens.diagnostics.shutil.which", return_value=None):
            report = doctor()
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["git"]["ok"])
        self.assertIn("PATH", report["checks"]["git"]["hint"])

    def test_doctor_has_failure_exit_code_without_opening_index(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch("repolens.cli.doctor", return_value={"ok": False}):
            with patch("repolens.cli.IndexStore", side_effect=AssertionError("must not open an index")):
                self.assertEqual(main(["doctor"]), 1)
        self.assertFalse(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
