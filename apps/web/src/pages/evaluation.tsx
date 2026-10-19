import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { ArrowUpRight } from 'lucide-react';
import { api, short } from '../api';
import {
  Badge,
  Empty,
  ErrorBox,
  EvidenceLink,
  Field,
  Loading,
  PageHeading,
  SourceDialog,
} from '../components';
import { useWorkspace } from '../state';
import type { Evaluation, Locator } from '../types';

const metricKeys = ['recall@5', 'recall@10', 'mrr', 'ndcg@10'];
export default function EvaluationPage() {
  const state = useWorkspace();
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ['evaluations'],
    queryFn: () => api<Evaluation[]>('/api/evaluations'),
  });
  const [group, setGroup] = useState('crossfile-v4');
  const [selectedId, setSelectedId] = useState('');
  const [failures, setFailures] = useState(true);
  const [caseId, setCaseId] = useState('');
  const [locator, setLocator] = useState<Locator | null>(null);
  const records = query.data?.filter((item) => item.group === group) || [];
  const selected =
    records.find((item) => item.id === selectedId) ||
    records.find((item) => item.run.strategy === 'graph') ||
    records[0];
  const cases = selected?.cases.filter((item) => !failures || item['recall@10'] < 1) || [];
  const selectedCase = selected?.cases.find((item) => item.id === caseId) || cases[0];
  const matchingSnapshot = state.workspace?.snapshots.find(
    (snapshot) => snapshot.commit_sha === selected?.run.commit_sha,
  );
  const data = metricKeys.map((key) => ({
    metric: key,
    ...Object.fromEntries(records.map((item) => [item.run.strategy, item.metrics[key]])),
  }));
  return (
    <>
      <PageHeading title="评测对比" count="冻结实验 · Flask" />
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : !selected ? (
        <Empty>暂无评测记录。</Empty>
      ) : (
        <>
          <div className="evaluation-toolbar">
            <Field label="评测集">
              <select
                value={group}
                onChange={(e) => {
                  setGroup(e.target.value);
                  setSelectedId('');
                  setCaseId('');
                }}
              >
                <option value="crossfile-v4">跨文件任务 · 10 题</option>
                <option value="validation-v4">原有验证集 · 20 题</option>
              </select>
            </Field>
            <div className="small muted mono">
              commit {short(selected.run.commit_sha)}
              <br />
              dataset {short(selected.run.dataset_sha256)}
            </div>
            <Badge tone="amber">同仓库评测</Badge>
          </div>
          <div className="evaluation-chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 15, right: 10, bottom: 10, left: -15 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend />
                {records.map((record, i) => (
                  <Bar
                    key={record.id}
                    dataKey={record.run.strategy}
                    isAnimationActive={false}
                    fill={['#5179b2', '#ba822d', '#098375'][i]}
                    radius={[2, 2, 0, 0]}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>检索策略</th>
                  {metricKeys.map((key) => (
                    <th key={key}>{key}</th>
                  ))}
                  <th>P50 / P95 ms</th>
                  <th>引用支持度</th>
                  <th>回答准确率</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <tr key={record.id} className={selected.id === record.id ? 'selected' : ''}>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => {
                          setSelectedId(record.id);
                          setCaseId('');
                        }}
                      >
                        {record.run.strategy}
                      </button>
                    </td>
                    {metricKeys.map((key) => (
                      <td key={key}>{Number(record.metrics[key]).toFixed(4)}</td>
                    ))}
                    <td>
                      {record.metrics.latency_ms.p50.toFixed(1)} /{' '}
                      {record.metrics.latency_ms.p95.toFixed(1)}
                    </td>
                    <td>未评测</td>
                    <td>未评测</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="evaluation-config">
            <summary>运行配置与来源</summary>
            <pre>{JSON.stringify(selected.run, null, 2)}</pre>
          </details>
          <div className="section-heading">
            <h2>
              单题证据链 <Badge>{selected.run.strategy}</Badge>
            </h2>
            <label className="check">
              <input
                type="checkbox"
                checked={failures}
                onChange={(e) => setFailures(e.target.checked)}
              />
              仅未完全召回
            </label>
          </div>
          <div className="evaluation-cases">
            <div className="case-list">
              {cases.length ? (
                cases.map((item) => (
                  <button
                    className={`case-item ${selectedCase?.id === item.id ? 'selected' : ''}`}
                    key={item.id}
                    onClick={() => setCaseId(item.id)}
                  >
                    <strong>
                      {item.id}
                      <Badge tone={item['recall@10'] < 1 ? 'amber' : 'green'}>
                        R@10 {item['recall@10'].toFixed(2)}
                      </Badge>
                    </strong>
                    <span>{item.query}</span>
                  </button>
                ))
              ) : (
                <Empty>当前筛选下没有失败样例。</Empty>
              )}
            </div>
            <section className="case-detail">
              {selectedCase ? (
                <>
                  <h2>{selectedCase.query}</h2>
                  <div className="actions">
                    <Badge>{selectedCase.category}</Badge>
                    <span className="small muted">
                      MRR {selectedCase.mrr.toFixed(3)} · {selectedCase.latency_ms.toFixed(1)} ms
                    </span>
                  </div>
                  <h3>人工标注的预期证据</h3>
                  {selectedCase.expected_evidence.map((item, i) => (
                    <div className="gold-item" key={i}>
                      {matchingSnapshot ? (
                        <EvidenceLink
                          item={{
                            path: item.path,
                            symbol: item.symbol,
                            snapshot_id: matchingSnapshot.snapshot_id,
                            commit_sha: matchingSnapshot.commit_sha,
                            line_start: item.line_start,
                            line_end: item.line_end,
                          }}
                          onOpen={setLocator}
                        />
                      ) : (
                        <code>{item.path}</code>
                      )}
                      <div className="small muted">
                        {item.symbol} · {item.line_start}–{item.line_end}
                      </div>
                    </div>
                  ))}
                  <h3>实际召回 · 前 10 条</h3>
                  {selectedCase.retrieved_evidence?.map((item, i) => (
                    <div className="gold-item" key={`${item.evidence_id}-${i}`}>
                      <span className="small muted">#{i + 1} </span>
                      {matchingSnapshot ? (
                        <EvidenceLink
                          item={{
                            ...item,
                            snapshot_id: matchingSnapshot.snapshot_id,
                            evidence_id:
                              matchingSnapshot.snapshot_id === item.snapshot_id
                                ? item.evidence_id
                                : undefined,
                          }}
                          onOpen={setLocator}
                        />
                      ) : (
                        <code className="small">
                          {item.path}:{item.line_start}
                        </code>
                      )}
                      <div className="small muted">{item.symbol || item.kind}</div>
                    </div>
                  ))}
                  <button
                    className="button secondary"
                    disabled={!matchingSnapshot}
                    title={
                      !matchingSnapshot
                        ? '先导入该实验 commit 的 Flask 仓库'
                        : '重新查看当前检索返回的证据'
                    }
                    onClick={() => {
                      state.setRef(selected.run.commit_sha);
                      navigate(
                        `/search?mode=search&question=${encodeURIComponent(selectedCase.query)}&retrieval=${selected.run.strategy}`,
                      );
                    }}
                  >
                    <ArrowUpRight size={15} />
                    查看当前检索证据
                  </button>
                </>
              ) : (
                <Empty>选择样例。</Empty>
              )}
            </section>
          </div>
        </>
      )}
      <SourceDialog
        locator={locator}
        onClose={() => setLocator(null)}
        workspaceId={state.workspaceId}
      />
    </>
  );
}
