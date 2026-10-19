import unittest
import json
from urllib.error import HTTPError, URLError

from repolens.answer import (
    ANSWER_SCHEMA_VERSION,
    abstained_answer,
    answer_schema,
    validate_provider_output,
)
from repolens.context import CONTEXT_HEADER, EvidenceContextPacker, estimate_tokens
from repolens.domain import RepoLensError
from repolens.pipeline import QuestionAnswerPipeline
from repolens.provider import DeepSeekProvider, MockProvider, ProviderRequest


def evidence(evidence_id="evidence-1", *, text="def run():\n    return 1\n", path="src/service.py"):
    return {
        "evidence_id": evidence_id,
        "snapshot_id": "snapshot-1",
        "commit_sha": "a" * 40,
        "path": path,
        "symbol": "run",
        "line_start": 1,
        "line_end": 2,
        "text": text,
    }


class FakeStore:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def search(self, query, snapshot_id, *, limit, path_prefix):
        self.calls.append((query, snapshot_id, limit, path_prefix))
        return self.results


class FakeHttpResponse:
    def __init__(self, body, *, headers=None):
        self.body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


class ProviderContractTests(unittest.TestCase):
    def test_request_rejects_empty_or_duplicate_context_ids(self):
        for kwargs in (
            {"question": "", "context": "context", "evidence_ids": ("E1",), "output_schema": "{}"},
            {"question": "question", "context": "", "evidence_ids": ("E1",), "output_schema": "{}"},
            {"question": "question", "context": "context", "evidence_ids": ("E1", "E1"), "output_schema": "{}"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(RepoLensError):
                ProviderRequest(**kwargs)

    def test_request_accepts_bounded_conversation_history(self):
        request = ProviderRequest(
            question="Where is it?",
            context="[E1] source",
            evidence_ids=("E1",),
            output_schema="{}",
            history=(
                {"role": "user", "content": "What does run do?"},
                {"role": "assistant", "content": "It runs."},
            ),
        )
        self.assertEqual(len(request.history), 2)
        with self.assertRaisesRegex(RepoLensError, "at most 8"):
            ProviderRequest(
                question="question",
                context="[E1] source",
                evidence_ids=("E1",),
                output_schema="{}",
                history=tuple({"role": "user", "content": "q"} for _ in range(9)),
            )

    def test_mock_provider_is_deterministic_and_records_request(self):
        request = ProviderRequest(
            question="What does run do?",
            context="[E1] source",
            evidence_ids=("E1",),
            output_schema="{}",
        )
        provider = MockProvider()
        first = provider.generate(request)
        second = provider.generate(request)
        self.assertEqual(first.output, second.output)
        self.assertEqual(first.provider, "mock")
        self.assertEqual(provider.last_request, request)
        self.assertEqual(len(provider.calls), 2)

    def test_deepseek_provider_uses_json_mode_and_parses_structured_response(self):
        output = {
            "status": "answered",
            "summary": "run returns one.",
            "claims": [{"text": "run returns one.", "citation_ids": ["E1"]}],
            "unknowns": [],
        }
        response = FakeHttpResponse(json.dumps({
            "model": "deepseek-flash",
            "choices": [{
                "message": {"content": json.dumps(output)},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
        }).encode(), headers={"x-request-id": "req-123"})
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return response

        request = ProviderRequest(
            question="What does run do?",
            context="[E1] source",
            evidence_ids=("E1",),
            output_schema='{"type":"object"}',
            max_output_tokens=128,
        )
        result = DeepSeekProvider(
            "test-secret",
            model="deepseek-flash",
            opener=opener,
            timeout_seconds=12,
            max_retries=0,
        ).generate(request)
        payload = json.loads(captured["request"].data)
        self.assertEqual(captured["request"].full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["timeout"], 12.0)
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["max_tokens"], 128)
        self.assertIn("JSON", payload["messages"][0]["content"])
        self.assertIn("[E1] source", payload["messages"][1]["content"])
        self.assertEqual(result.output, output)
        self.assertEqual(result.usage["total_tokens"], 35)
        self.assertEqual(result.request_id, "req-123")
        self.assertEqual(result.attempts, 1)
        self.assertIsInstance(result.latency_ms, int)

    def test_deepseek_agent_plan_uses_closed_json_protocol_and_zero_temperature(self):
        plan = {"action": "finish", "tool": None, "arguments": {}}
        response = FakeHttpResponse(json.dumps({"choices": [{
            "message": {"content": json.dumps(plan)}, "finish_reason": "stop",
        }]}).encode())
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data))
            return response

        provider = DeepSeekProvider("test-secret", opener=opener, max_retries=0)
        request = ProviderRequest(question="Where is run?", context="[E1] untrusted source",
                                  evidence_ids=("E1",), output_schema='{"type":"object"}',
                                  metadata={"purpose": "agent_plan"})
        self.assertEqual(provider.generate(request).output, plan)
        self.assertEqual(captured[0]["temperature"], 0)
        self.assertEqual(captured[0]["response_format"], {"type": "json_object"})
        self.assertIn("host-provided tools", captured[0]["messages"][0]["content"])
        self.assertNotIn("test-secret", json.dumps(captured))

    def test_default_deepseek_configuration_can_cross_spawn_boundary(self):
        import pickle

        provider = pickle.loads(pickle.dumps(DeepSeekProvider("fixture-only", max_retries=0)))
        self.assertEqual(DeepSeekProvider.DEFAULT_MODEL, "deepseek-flash")
        self.assertEqual(provider.model, DeepSeekProvider.DEFAULT_MODEL)
        self.assertEqual(provider.max_retries, 0)

    def test_deepseek_provider_retries_transient_network_failure(self):
        output = {"status": "abstained", "summary": "unknown", "claims": [], "unknowns": ["unknown"]}
        response = FakeHttpResponse(json.dumps({
            "choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
        }).encode())
        calls = []

        def opener(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise URLError("temporary")
            return response

        sleeps = []
        provider = DeepSeekProvider("test-secret", opener=opener, max_retries=1, sleeper=sleeps.append)
        result = provider.generate(ProviderRequest(
            question="question", context="[E1] source", evidence_ids=("E1",), output_schema="{}"
        ))
        self.assertEqual(result.output["status"], "abstained")
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1.0])

    def test_deepseek_provider_fails_without_key_and_does_not_retry_auth_error(self):
        with self.assertRaisesRegex(RepoLensError, "DEEPSEEK_API_KEY"):
            DeepSeekProvider("")

        calls = []

        def opener(request, timeout):
            calls.append(1)
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

        with self.assertRaisesRegex(RepoLensError, "HTTP 401"):
            DeepSeekProvider("test-secret", opener=opener, max_retries=3, sleeper=lambda _: self.fail("retried"))\
                .generate(ProviderRequest(
                    question="question", context="[E1] source", evidence_ids=("E1",), output_schema="{}"
                ))
        self.assertEqual(len(calls), 1)

    def test_deepseek_provider_rejects_invalid_json_content(self):
        response = FakeHttpResponse(json.dumps({
            "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
        }).encode())
        with self.assertRaisesRegex(RepoLensError, "not valid JSON"):
            DeepSeekProvider("test-secret", opener=lambda request, timeout: response).generate(
                ProviderRequest(
                    question="question", context="[E1] source", evidence_ids=("E1",), output_schema="{}"
                )
            )

    def test_deepseek_provider_rejects_oversized_response(self):
        oversized = FakeHttpResponse(b"x" * (DeepSeekProvider.MAX_RESPONSE_BYTES + 1))
        with self.assertRaisesRegex(RepoLensError, "4 MiB"):
            DeepSeekProvider("test-secret", opener=lambda request, timeout: oversized).generate(
                ProviderRequest(
                    question="question", context="[E1] source", evidence_ids=("E1",), output_schema="{}"
                )
            )

    def test_provider_request_rejects_unbounded_output_budget(self):
        with self.assertRaisesRegex(RepoLensError, "between 1 and 8192"):
            ProviderRequest(
                question="question",
                context="[E1] source",
                evidence_ids=("E1",),
                output_schema="{}",
                max_output_tokens=8193,
            )


class ContextPackingTests(unittest.TestCase):
    def test_packer_keeps_evidence_atomic_and_reports_dropped_ids(self):
        first = evidence("evidence-1", text="first line\nsecond line\n")
        second = evidence("evidence-2", text="second evidence with more source text\n")
        full = EvidenceContextPacker(token_budget=2000).pack([first, second])
        first_budget = estimate_tokens(CONTEXT_HEADER + full.items[0].rendered)
        limited = EvidenceContextPacker(token_budget=first_budget).pack([first, second])
        self.assertEqual([item.evidence_id for item in limited.items], ["evidence-1"])
        self.assertEqual(limited.dropped_evidence_ids, ("evidence-2",))
        self.assertIn("first line\nsecond line\n", limited.rendered)
        self.assertLessEqual(limited.tokens_used, first_budget)

    def test_packer_deduplicates_identical_records_and_rejects_conflicts(self):
        record = evidence()
        packed = EvidenceContextPacker().pack([record, record])
        self.assertEqual(len(packed.items), 1)
        with self.assertRaisesRegex(RepoLensError, "conflicting"):
            EvidenceContextPacker().pack([record, record | {"text": "other\n"}])

    def test_packer_rejects_unsafe_paths(self):
        with self.assertRaisesRegex(RepoLensError, "safe repository"):
            EvidenceContextPacker().pack([evidence(path="../outside.py")])


class AnswerValidationTests(unittest.TestCase):
    def setUp(self):
        self.context = EvidenceContextPacker().pack([evidence()])

    def test_schema_has_strict_provider_contract(self):
        schema = answer_schema()
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], ["status", "summary", "claims", "unknowns"])
        self.assertEqual(len(schema["oneOf"]), 2)

    def test_valid_answer_gets_canonical_citation_locator(self):
        answer = validate_provider_output(
            {
                "status": "answered",
                "summary": "run returns one.",
                "claims": [{"text": "run returns one.", "citation_ids": ["E1"]}],
                "unknowns": [],
            },
            self.context,
            "What does run do?",
            provider="mock",
            model="mock-deterministic-v1",
            trace_id="trace-1",
        )
        self.assertEqual(answer.schema_version, ANSWER_SCHEMA_VERSION)
        self.assertEqual(answer.status, "answered")
        self.assertEqual(answer.citations[0].evidence_id, "evidence-1")
        self.assertEqual(answer.citations[0].path, "src/service.py")
        self.assertEqual(answer.trace_id, "trace-1")

    def test_unknown_or_missing_citation_is_rejected(self):
        unknown = {
            "status": "answered",
            "summary": "answer",
            "claims": [{"text": "claim", "citation_ids": ["E9"]}],
            "unknowns": [],
        }
        missing = unknown | {"claims": [{"text": "claim", "citation_ids": []}]}
        for output in (unknown, missing):
            with self.subTest(output=output), self.assertRaises(RepoLensError):
                validate_provider_output(
                    output, self.context, "question", provider="mock", model="mock"
                )

    def test_answer_limits_reject_model_output_bursts(self):
        too_many_claims = {
            "status": "answered",
            "summary": "answer",
            "claims": [
                {"text": "claim", "citation_ids": ["E1"]}
                for _ in range(65)
            ],
            "unknowns": [],
        }
        with self.assertRaisesRegex(RepoLensError, "at most 64"):
            validate_provider_output(
                too_many_claims, self.context, "question", provider="mock", model="mock"
            )

    def test_abstention_is_valid_without_citations(self):
        answer = validate_provider_output(
            {
                "status": "abstained",
                "summary": "Insufficient evidence.",
                "claims": [],
                "unknowns": ["The repository does not show this behavior."],
            },
            self.context,
            "question",
            provider="none",
            model="none",
        )
        self.assertEqual(answer.status, "abstained")
        self.assertEqual(answer.citations, ())
        self.assertEqual(abstained_answer("question", "reason").status, "abstained")


class PipelineTests(unittest.TestCase):
    def test_no_evidence_abstains_before_provider_call(self):
        provider = MockProvider()
        pipeline = QuestionAnswerPipeline(FakeStore([]), "snapshot-1", provider)
        result = pipeline.answer("unanswerable question")
        self.assertEqual(result.answer.status, "abstained")
        self.assertEqual(provider.calls, [])
        self.assertEqual(result.context.tokens_used, 0)

    def test_budget_exhaustion_abstains_before_provider_call(self):
        provider = MockProvider()
        pipeline = QuestionAnswerPipeline(
            FakeStore([evidence(text="x" * 1000)]),
            "snapshot-1",
            provider,
            context_packer=EvidenceContextPacker(token_budget=1),
        )
        result = pipeline.answer("question")
        self.assertEqual(result.answer.status, "abstained")
        self.assertEqual(provider.calls, [])

    def test_success_sends_only_packed_citations_and_validates_answer(self):
        provider = MockProvider()
        pipeline = QuestionAnswerPipeline(FakeStore([evidence()]), "snapshot-1", provider)
        result = pipeline.answer("What does run do?", limit=3)
        self.assertEqual(result.answer.status, "answered")
        self.assertEqual(result.answer.citations[0].citation_id, "E1")
        self.assertEqual(provider.last_request.evidence_ids, ("E1",))
        self.assertIn("repolens.answer.v1", provider.last_request.output_schema)
        self.assertEqual(result.answer.trace_id, result.telemetry.trace_id)
        self.assertEqual(result.telemetry.provider, "mock")
        self.assertEqual(result.telemetry.attempts, 1)
        self.assertIn("telemetry", result.to_dict())

    def test_follow_up_history_contributes_user_terms_to_retrieval(self):
        provider = MockProvider()
        store = FakeStore([evidence()])
        pipeline = QuestionAnswerPipeline(store, "snapshot-1", provider)
        pipeline.answer(
            "Where is it?",
            history=({"role": "user", "content": "What does run do?"},),
        )
        self.assertIn("What does run do? Where is it?", store.calls[0][0])
        self.assertEqual(provider.last_request.history[0]["role"], "user")

    def test_malformed_provider_answer_fails_closed(self):
        provider = MockProvider({
            "status": "answered",
            "summary": "hallucinated",
            "claims": [{"text": "unsupported", "citation_ids": ["E9"]}],
            "unknowns": [],
        })
        pipeline = QuestionAnswerPipeline(FakeStore([evidence()]), "snapshot-1", provider)
        with self.assertRaisesRegex(RepoLensError, "unknown or un-packed"):
            pipeline.answer("question")

    def test_abstention_triggers_one_bounded_follow_up_and_retries_generation(self):
        outputs = iter((
            {
                "status": "abstained",
                "summary": "The first result is insufficient.",
                "claims": [],
                "unknowns": ["Need the implementation symbol."],
            },
            {
                "status": "answered",
                "summary": "run returns one.",
                "claims": [{"text": "run returns one.", "citation_ids": ["E1"]}],
                "unknowns": [],
            },
        ))
        provider = MockProvider(lambda request: next(outputs))
        first = evidence(text="def run():\n    return 1\n")
        second = evidence("evidence-2", text="def helper():\n    return 2\n", path="src/helper.py")
        store = FakeStore([first])
        store.results = [first]

        original_search = store.search
        def search(query, snapshot_id, *, limit, path_prefix):
            original_search(query, snapshot_id, limit=limit, path_prefix=path_prefix)
            return [first] if len(store.calls) == 1 else [second]

        store.search = search
        result = QuestionAnswerPipeline(
            store, "snapshot-1", provider, max_follow_up_searches=1,
        ).answer("What does run do?")

        self.assertEqual(result.answer.status, "answered")
        self.assertEqual(result.telemetry.retrieval_rounds, 2)
        self.assertEqual(result.telemetry.generation_rounds, 2)
        self.assertEqual(result.telemetry.follow_up_searches, 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(result.retrieval_queries), 2)
        self.assertEqual(result.answer.citations[0].evidence_id, "evidence-2")

    def test_follow_up_budget_is_hard_bounded(self):
        provider = MockProvider({
            "status": "abstained",
            "summary": "Insufficient evidence.",
            "claims": [],
            "unknowns": ["Unknown."],
        })
        store = FakeStore([evidence()])
        result = QuestionAnswerPipeline(
            store, "snapshot-1", provider, max_follow_up_searches=3,
        ).answer("What does run do?")
        self.assertEqual(result.answer.status, "abstained")
        self.assertLessEqual(len(provider.calls), 4)
        self.assertLessEqual(result.telemetry.follow_up_searches, 3)
        self.assertLessEqual(result.telemetry.retrieval_rounds, 4)

        with self.assertRaisesRegex(RepoLensError, "between 0 and 3"):
            QuestionAnswerPipeline(store, "snapshot-1", provider, max_follow_up_searches=4)


if __name__ == "__main__":
    unittest.main()
