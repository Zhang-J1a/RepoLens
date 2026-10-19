"""Offline contracts for the optional LangChain provider and retriever."""

import json
from dataclasses import asdict
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

LANGCHAIN_AVAILABLE = all(importlib.util.find_spec(name) is not None
                          for name in ("langchain_core", "langchain_deepseek"))
if LANGCHAIN_AVAILABLE:
    import langchain_deepseek  # noqa: F401
    from langchain_core.runnables import RunnableLambda

from repolens.domain import RepoLensError
from repolens.pipeline import QuestionAnswerPipeline
from repolens.provider import MockProvider, ProviderRequest


def evidence():
    return {
        "evidence_id": "evidence-unit-1",
        "snapshot_id": "snapshot-unit",
        "repository_id": "repository-unit",
        "commit_sha": "a" * 40,
        "path": "src/service.py",
        "blob_id": "blob-unit",
        "content_hash": "hash-unit",
        "symbol": "dispatch",
        "kind": "function",
        "line_start": 1,
        "line_end": 2,
        "text": "def dispatch(value):\n    return value + 1\n",
        "hybrid_score": 0.02,
    }


@unittest.skipUnless(LANGCHAIN_AVAILABLE, "Install the optional 'langchain' extra")
class LangChainIntegrationTests(unittest.TestCase):
    def test_environment_configuration_and_explicit_overrides(self):
        from repolens.langchain_integration import LangChainDeepSeekProvider

        environment = {"DEEPSEEK_API_KEY": "offline-test-key", "DEEPSEEK_MODEL": "model-env",
                       "DEEPSEEK_BASE_URL": "https://api.deepseek.com", "DEEPSEEK_TIMEOUT_SECONDS": "12.5",
                       "DEEPSEEK_MAX_RETRIES": "1"}
        with patch.dict("os.environ", environment):
            provider = LangChainDeepSeekProvider.from_environment()
            overridden = LangChainDeepSeekProvider.from_environment(model="model-cli", timeout_seconds=5, max_retries=0)
        self.assertEqual((provider.model, provider.timeout_seconds, provider.max_retries), ("model-env", 12.5, 1))
        self.assertEqual(provider.base_url, "https://api.deepseek.com/v1")
        self.assertEqual((overridden.model, overridden.timeout_seconds, overridden.max_retries), ("model-cli", 5, 0))
        with patch.dict("os.environ", environment | {"DEEPSEEK_MAX_RETRIES": "invalid"}):
            with self.assertRaises(RepoLensError):
                LangChainDeepSeekProvider.from_environment()

    def test_real_langchain_deepseek_chain_constructs_without_remote_call(self):
        from langchain_core.runnables import Runnable
        from repolens.langchain_integration import LangChainDeepSeekProvider

        provider = LangChainDeepSeekProvider("offline-test-key", model="deepseek-test", max_retries=0)
        request = ProviderRequest(
            question="What does dispatch do?", context="[E1] dispatch source",
            evidence_ids=("E1",), output_schema='{"type":"object"}', max_output_tokens=64,
        )
        chain = provider._build_chain(request)
        self.assertIsInstance(chain, Runnable)

    def test_retriever_preserves_snapshot_and_evidence_provenance(self):
        from repolens.langchain_integration import RepoLensRetriever

        class Store:
            def search_hybrid(self, query, snapshot_id, *, limit, path_prefix):
                self.call = (query, snapshot_id, limit, path_prefix)
                return [evidence()]

        store = Store()
        retriever = RepoLensRetriever(store=store, snapshot_id="snapshot-unit", strategy="hybrid",
                                      limit=4, path_prefix="src")
        documents = retriever.invoke("dispatch")
        self.assertEqual(store.call, ("dispatch", "snapshot-unit", 4, "src"))
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].id, "evidence-unit-1")
        self.assertEqual(documents[0].metadata["commit_sha"], "a" * 40)
        self.assertEqual(documents[0].metadata["line_start"], 1)
        self.assertIn("return value + 1", documents[0].page_content)

    def test_retriever_rejects_wrong_snapshot_or_missing_evidence(self):
        from repolens.langchain_integration import RepoLensRetriever

        class Store:
            def search_hybrid(self, *args, **kwargs):
                return [self.hit]

        store = Store()
        retriever = RepoLensRetriever(store=store, snapshot_id="snapshot-unit", strategy="hybrid", limit=2)
        for changes in ({"snapshot_id": "snapshot-other"}, {"evidence_id": None}, {"text": ""}):
            with self.subTest(changes=changes):
                store.hit = evidence() | changes
                with self.assertRaises(RepoLensError):
                    retriever.invoke("dispatch")

    def test_pipeline_uses_langchain_retriever_and_keeps_native_citation_validation(self):
        from repolens.langchain_integration import RepoLensRetriever

        class Store:
            def search_hybrid(self, query, snapshot_id, *, limit, path_prefix):
                return [evidence()]

        result = QuestionAnswerPipeline(
            Store(), "snapshot-unit", MockProvider(), retrieval_strategy="hybrid",
            retriever_factory=RepoLensRetriever,
        ).answer("What does dispatch return?", limit=2)
        self.assertEqual(result.answer.status, "answered")
        self.assertEqual(result.answer.citations[0].evidence_id, "evidence-unit-1")
        self.assertEqual(result.answer.citations[0].snapshot_id, "snapshot-unit")
        invalid = MockProvider(output={"status": "answered", "summary": "Invalid.",
                                       "claims": [{"text": "Invalid.", "citation_ids": ["E999"]}], "unknowns": []})
        with self.assertRaises(RepoLensError):
            QuestionAnswerPipeline(Store(), "snapshot-unit", invalid, retrieval_strategy="hybrid",
                                   retriever_factory=RepoLensRetriever).answer("dispatch", limit=2)

    def test_real_langchain_parser_normalizes_mocked_chat_result(self):
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_deepseek import ChatDeepSeek
        from repolens.langchain_integration import LangChainDeepSeekProvider

        output = {"status": "abstained", "summary": "Unknown.", "claims": [], "unknowns": ["Unknown."]}
        raw = AIMessage(content=json.dumps(output), response_metadata={"finish_reason": "stop"},
                        usage_metadata={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18})
        provider = LangChainDeepSeekProvider("offline-test-key", max_retries=0)
        with patch.object(ChatDeepSeek, "_generate", return_value=ChatResult(
                generations=[ChatGeneration(message=raw)])):
            result = provider.generate(ProviderRequest(
                question="Question", context="[E1] Evidence", evidence_ids=("E1",), output_schema='{"type":"object"}',
            ))
        self.assertEqual(result.output, output)
        self.assertEqual(result.usage["total_tokens"], 18)

    def test_adapter_disables_remote_tracing_even_when_environment_enables_it(self):
        from langsmith.run_helpers import get_tracing_context
        from repolens.langchain_integration import LangChainDeepSeekProvider, RepoLensRetriever

        observed = []

        class Store:
            def search_hybrid(self, *args, **kwargs):
                observed.append(get_tracing_context()["enabled"])
                return [evidence()]

        def respond(_):
            observed.append(get_tracing_context()["enabled"])
            return {"raw": None, "parsed": {"status": "abstained"}, "parsing_error": None}

        retriever = RepoLensRetriever(store=Store(), snapshot_id="snapshot-unit", strategy="hybrid", limit=2)
        provider = LangChainDeepSeekProvider("offline-test-key", max_retries=0)
        with patch.dict("os.environ", {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"}):
            retriever.invoke("dispatch")
            with patch.object(provider, "_build_chain", return_value=RunnableLambda(respond)):
                provider.generate(ProviderRequest(
                    question="Question", context="[E1] Evidence", evidence_ids=("E1",), output_schema="{}",
                ))
        self.assertEqual(observed, [False, False])

    def test_truncated_or_oversized_output_is_rejected(self):
        from repolens.langchain_integration import LangChainDeepSeekProvider

        provider = LangChainDeepSeekProvider("offline-test-key", max_retries=0)
        for raw, parsed in (
            (SimpleNamespace(response_metadata={"finish_reason": "length"}), {"status": "abstained"}),
            (None, {"summary": "x" * (provider.MAX_RESPONSE_BYTES + 1)}),
        ):
            with self.subTest(truncated=raw is not None):
                with self.assertRaises(RepoLensError):
                    provider._response({"raw": raw, "parsed": parsed, "parsing_error": None}, 1, 0)

    def test_lcel_chain_requests_structured_json_and_normalizes_safe_metadata(self):
        from repolens.langchain_integration import LangChainDeepSeekProvider

        output = {"status": "answered", "summary": "Dispatch adds one.",
                  "claims": [{"text": "It adds one.", "citation_ids": ["E1"]}], "unknowns": []}
        captured = {}

        class FakeChatDeepSeek:
            def __init__(self, **kwargs):
                captured["model_config"] = kwargs

            def with_structured_output(self, schema, *, method, include_raw):
                captured["schema"], captured["method"], captured["include_raw"] = schema, method, include_raw

                def respond(prompt):
                    messages = prompt.to_messages()
                    captured["system"] = messages[0].content
                    captured["human"] = messages[1].content
                    raw = SimpleNamespace(response_metadata={
                        "id": "request-langchain-unit", "model_name": "deepseek-test", "finish_reason": "stop",
                    }, usage_metadata={"input_tokens": 21, "output_tokens": 7, "total_tokens": 28})
                    return {"raw": raw, "parsed": output, "parsing_error": None}

                return RunnableLambda(respond)

        module = ModuleType("langchain_deepseek")
        module.ChatDeepSeek = FakeChatDeepSeek
        provider = LangChainDeepSeekProvider("unit-secret", model="deepseek-test", max_retries=0)
        request = ProviderRequest(
            question="What does dispatch do?", context="[E1] dispatch source",
            evidence_ids=("E1",), output_schema='{"type":"object"}', max_output_tokens=64,
            history=({"role": "user", "content": "Previous question"},),
        )
        with patch.dict(sys.modules, {"langchain_deepseek": module}):
            result = provider.generate(request)
        self.assertEqual(captured["method"], "json_mode")
        self.assertTrue(captured["include_raw"])
        self.assertEqual(captured["schema"], {"type": "object"})
        self.assertEqual(captured["model_config"]["api_key"], "unit-secret")
        self.assertEqual(captured["model_config"]["max_retries"], 0)
        self.assertIn("untrusted data", captured["system"])
        self.assertIn("Previous question", captured["human"])
        self.assertIn("[E1] dispatch source", captured["human"])
        self.assertEqual(result.output, output)
        self.assertEqual(result.usage["total_tokens"], 28)
        self.assertEqual(result.request_id, "request-langchain-unit")
        self.assertNotIn("unit-secret", json.dumps(asdict(result)))

    def test_retry_is_bounded_and_reports_observed_attempts(self):
        from repolens.langchain_integration import LangChainDeepSeekProvider

        output = {"status": "abstained", "summary": "Unknown.", "claims": [], "unknowns": ["Unknown."]}
        calls = []

        class RetryableError(Exception):
            status_code = 503

        def invoke(_):
            calls.append(1)
            if len(calls) == 1:
                raise RetryableError("do not expose this")
            raw = SimpleNamespace(response_metadata={}, usage_metadata={})
            return {"raw": raw, "parsed": output, "parsing_error": None}

        provider = LangChainDeepSeekProvider("unit-secret", max_retries=1)
        with patch.object(provider, "_build_chain", return_value=RunnableLambda(invoke)):
            with patch("repolens.langchain_integration.time.sleep") as sleep:
                result = provider.generate(ProviderRequest(
                    question="Question", context="[E1] Evidence", evidence_ids=("E1",), output_schema="{}",
                ))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleep.call_args.args, (1.0,))

    def test_invalid_status_is_not_retried_or_leaked(self):
        from repolens.langchain_integration import LangChainDeepSeekProvider

        class Unauthorized(Exception):
            status_code = 401

        provider = LangChainDeepSeekProvider("unit-secret", max_retries=4)
        with patch.object(provider, "_build_chain", return_value=RunnableLambda(lambda _: (_ for _ in ()).throw(
                Unauthorized("unit-secret must not leak")))):
            with self.assertRaisesRegex(RepoLensError, "HTTP 401") as raised:
                provider.generate(ProviderRequest(
                    question="Question", context="[E1] Evidence", evidence_ids=("E1",), output_schema="{}",
                ))
        self.assertNotIn("unit-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
