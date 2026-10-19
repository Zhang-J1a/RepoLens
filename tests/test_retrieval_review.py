import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from experiments.retrieval_review import (
    EXPERIMENT_POLICY, fts_candidates, identifier_subqueries, legacy_expression,
    reciprocal_rank_fusion, run_review, verify_scores,
)
from repolens.domain import RepoLensError
from repolens.evaluation import METRIC_KEYS, evaluate_dataset
from repolens.git import _environment
from repolens.index import IndexStore, match_expression
from repolens.ingestion import ingest


class FusionTests(unittest.TestCase):
    def test_legacy_expression_does_not_duplicate_current_phrases(self):
        query = 'Queue.drain_batch before_ack'
        old = legacy_expression(query)
        current = match_expression(query)
        self.assertEqual(old, '"Queue" OR "drain" OR "batch" OR "before" OR "ack"')
        self.assertEqual(current.count('"Queue.drain_batch"'), 1)
        self.assertEqual(current.count('"before_ack"'), 1)

    def test_subqueries_are_bounded_deduplicated_and_do_not_invent_names(self):
        self.assertEqual(identifier_subqueries('Queue.drain_batch. before_ack before_ack extra_name'),
                         ['"queue.drain_batch"', '"drain_batch"', '"before_ack"'])
        self.assertEqual(identifier_subqueries('How does a queue work?'), [])
        self.assertEqual(identifier_subqueries('OR "drop_table" *'), ['"drop_table"'])
        with self.assertRaises(RepoLensError):
            identifier_subqueries('x' * 4097)

    def test_rrf_uses_ranks_and_deduplicates_per_route(self):
        def row(identity, score):
            return {"id": identity, "path": identity + '.py', "line_start": 1, "bm25_score": score}
        a, b, c = row('a', -900), row('b', -1), row('c', -800)
        result = reciprocal_rank_fusion([[a, a, b], [b, c]])
        self.assertEqual([r['id'] for r in result], ['b', 'a', 'c'])
        self.assertAlmostEqual(result[0]['rrf_score'], 1 / 63 + 1 / 61)
        self.assertAlmostEqual(result[1]['rrf_score'], 1 / 61)
        self.assertEqual(reciprocal_rank_fusion([]), [])


class ReviewReplayTests(unittest.TestCase):
    def test_replay_rejects_changed_metrics_and_isolates_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo, data = base / 'repo', base / 'index'
            repo.mkdir()
            env = _environment() | {"GIT_CONFIG_NOSYSTEM": '1', "GIT_CONFIG_GLOBAL": os.devnull}

            def git(*args):
                return subprocess.run(
                    ['git', '-c', 'init.templateDir=', '-c', 'core.autocrlf=false',
                     '-c', 'user.name=RepoLens Test', '-c', 'user.email=test@example.invalid',
                     '-C', str(repo), *args], env=env, capture_output=True, check=True, timeout=30,
                ).stdout.decode().strip()

            git('init', '--quiet')
            source = repo / 'service.py'
            source.write_text('def drain_batch():\n    return "oldmarker"\n', encoding='utf-8')
            git('add', '--all')
            git('commit', '--quiet', '--no-gpg-sign', '-m', 'old')
            old = ingest(repo, data)
            source.write_text('def future_batch():\n    return "futuremarker"\n', encoding='utf-8')
            git('add', '--all')
            git('commit', '--quiet', '--no-gpg-sign', '-m', 'new')
            ingest(repo, data)
            dataset = base / 'cases.jsonl'
            dataset.write_text(json.dumps({
                'id': 'queue-1', 'repo': 'test/queue', 'commit_sha': old['commit_sha'],
                'category': 'batching', 'query': 'drain_batch', 'expected_behavior': 'Return marker.',
                'expected_evidence': [{'path': 'service.py', 'symbol': 'drain_batch',
                                       'line_start': 1, 'line_end': 2}],
            }) + '\n', encoding='utf-8')
            with IndexStore(data) as store:
                frozen = evaluate_dataset(dataset, store, old['snapshot_id'])
                # A single matching chunk has analytically perfect scores in both policies.
                self.assertTrue(all(frozen['metrics'][key] == 1.0 for key in METRIC_KEYS))
                baseline = base / 'baseline.json'
                baseline.write_text(json.dumps(frozen), encoding='utf-8')
                paths = {'v1.2': baseline, 'v1.3': baseline}
                before = git('status', '--porcelain')
                report = run_review(dataset, store, old['snapshot_id'], paths)
                self.assertTrue(report['run']['frozen_scores_reproduced'])
                self.assertEqual(report['metrics'][EXPERIMENT_POLICY]['recall@10'], 1.0)
                self.assertEqual(report['experiment']['fts_query_count_distribution'], {2: 1})
                self.assertNotIn('"text":', json.dumps(report))
                self.assertNotIn('oldmarker', json.dumps(report))
                self.assertFalse(fts_candidates(store, old['snapshot_id'], '"futuremarker"'))
                self.assertEqual(git('status', '--porcelain'), before)
                with self.assertRaises(sqlite3.OperationalError):
                    store.connection.execute('DELETE FROM snapshots')
                changed = copy.deepcopy(frozen)
                changed['cases'][0]['recall@10'] = 0.0
                with self.assertRaisesRegex(RepoLensError, 'Frozen score mismatch'):
                    verify_scores(frozen['cases'], changed)
                changed['run']['dataset_sha256'] = 'bad'
                baseline.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaisesRegex(RepoLensError, 'metadata mismatch'):
                    run_review(dataset, store, old['snapshot_id'], paths)
