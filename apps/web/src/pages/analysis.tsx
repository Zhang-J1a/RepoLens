import { useState } from 'react';
import { GitCompareArrows, Play } from 'lucide-react';
import {
  Badge,
  DiffView,
  Empty,
  ErrorBox,
  EvidenceLink,
  EvidenceList,
  ExportButtons,
  Field,
  PageHeading,
  RequireWorkspace,
  SourceDialog,
  TaskProgress,
  useTask,
  AnswerView,
} from '../components';
import { useWorkspace } from '../state';
import type { ImpactResult, Locator } from '../types';
import { short } from '../api';

export default function AnalysisPage() {
  return (
    <>
      <PageHeading title="变更分析" />
      <RequireWorkspace>
        <Analysis />
      </RequireWorkspace>
    </>
  );
}
function Analysis() {
  const state = useWorkspace();
  const [base, setBase] = useState('HEAD~1');
  const [diff, setDiff] = useState('');
  const [withGraph, setWithGraph] = useState(true);
  const [locator, setLocator] = useState<Locator | null>(null);
  const [selectedFile, setSelectedFile] = useState('');
  const [tab, setTab] = useState('files');
  const task = useTask('analysis');
  const report = task.task?.result as ImpactResult | undefined;
  const selectedPath = report?.changed_files.some((file) => file.path === selectedFile)
    ? selectedFile
    : report?.changed_files[0]?.path || '';
  return (
    <>
      <form
        className="analysis-form"
        onSubmit={(e) => {
          e.preventDefault();
          task.start({
            action: 'impact',
            workspace_id: state.workspaceId,
            ref: state.ref,
            base,
            provider: state.provider,
            with_graph: withGraph,
            diff,
          });
        }}
      >
        <div className="form-grid">
          <Field label="Base commit / 分支">
            <input value={base} onChange={(e) => setBase(e.target.value)} required />
          </Field>
          <GitCompareArrows size={20} className="form-arrow" />
          <Field label="Head commit / 分支">
            <input value={state.ref} onChange={(e) => state.setRef(e.target.value)} required />
          </Field>
          <button className="button" disabled={task.pending}>
            <Play size={15} />
            分析变更
          </button>
        </div>
        <div className="form-options">
          <label className="check">
            <input
              type="checkbox"
              checked={withGraph}
              onChange={(e) => setWithGraph(e.target.checked)}
            />
            图增强影响分析
          </label>
          <Badge>{state.provider}</Badge>
          <details>
            <summary>PR diff</summary>
            <textarea
              aria-label="PR diff"
              value={diff}
              onChange={(e) => setDiff(e.target.value)}
              placeholder="粘贴与本地 base/head 对应的 unified diff"
              maxLength={100000}
            />
          </details>
        </div>
      </form>
      <ErrorBox error={task.error} />
      <TaskProgress task={task.task} />
      {!report ? (
        <Empty>选择提交范围后查看变更、风险与证据。</Empty>
      ) : (
        <>
          <div className="report-heading">
            <div>
              <h2>{report.summary}</h2>
              <span className="small mono muted">
                {short(report.base.commit_sha)} → {short(report.head.commit_sha)}
              </span>
            </div>
            <div className="actions">
              <ExportButtons task={task.task} markdown />
            </div>
          </div>
          <div className="metrics-strip">
            <div className="metric">
              <span>变更文件</span>
              <strong>{report.changed_files.length}</strong>
            </div>
            <div className="metric">
              <span>变化符号</span>
              <strong>
                {report.changed_files.reduce((n, file) => n + file.symbols.length, 0)}
              </strong>
            </div>
            <div className="metric">
              <span>候选风险</span>
              <strong>{report.risks.length}</strong>
            </div>
            <div className="metric">
              <span>证据</span>
              <strong>{report.evidence.length}</strong>
            </div>
          </div>
          <div className="tabs" role="tablist">
            {[
              ['files', '文件与 Diff'],
              ['risks', '风险与测试'],
              ['evidence', '相关证据'],
              ['unknowns', '不确定性'],
            ].map(([key, label]) => (
              <button
                role="tab"
                aria-selected={tab === key}
                key={key}
                onClick={() => setTab(key)}
                className={tab === key ? 'active' : ''}
              >
                {label}
              </button>
            ))}
          </div>
          {tab === 'files' && (
            <div className="analysis-grid">
              <div className="change-file-list">
                {report.changed_files.map((file) => (
                  <button
                    className={`change-file ${selectedPath === file.path ? 'selected' : ''}`}
                    key={file.path}
                    onClick={() => setSelectedFile(file.path)}
                  >
                    <Badge tone={file.status === 'D' ? 'red' : 'green'}>{file.status}</Badge>
                    <span>
                      {file.path}
                      <small>
                        {file.category} · {file.symbols.length} 个符号
                      </small>
                    </span>
                  </button>
                ))}
              </div>
              <div className="diff-pane">
                <DiffView
                  workspaceId={state.workspaceId}
                  base={report.base.snapshot_id}
                  head={report.head.snapshot_id}
                  path={selectedPath}
                />
                <div className="symbol-list">
                  {report.changed_files
                    .find((file) => file.path === selectedPath)
                    ?.symbols.map((symbol, i) => {
                      const evidence = report.evidence.find(
                        (e) => e.evidence_id === symbol.evidence_id,
                      );
                      return (
                        <div key={i}>
                          <Badge>{symbol.change}</Badge>
                          {evidence ? (
                            <EvidenceLink item={evidence} onOpen={setLocator}>
                              {symbol.name}
                            </EvidenceLink>
                          ) : (
                            <span>{symbol.name}</span>
                          )}
                        </div>
                      );
                    })}
                </div>
              </div>
            </div>
          )}
          {tab === 'risks' && (
            <div className="report-grid">
              <section>
                <h2>风险</h2>
                {report.risks.length ? (
                  report.risks.map((risk, i) => (
                    <article className="risk-item" key={i}>
                      <div className="actions">
                        <Badge
                          tone={
                            ['high', 'blocking'].includes(risk.severity)
                              ? 'red'
                              : risk.severity === 'medium'
                                ? 'amber'
                                : ''
                          }
                        >
                          {risk.severity}
                        </Badge>
                        <Badge>推测</Badge>
                      </div>
                      <p>{risk.reason}</p>
                      <span className="small mono muted">{risk.path}</span>
                      {risk.evidence_ids.map((id) => {
                        const evidence = report.evidence.find((e) => e.evidence_id === id);
                        return evidence ? (
                          <EvidenceLink key={id} item={evidence} onOpen={setLocator} />
                        ) : null;
                      })}
                    </article>
                  ))
                ) : (
                  <Empty>规则未识别到候选风险。</Empty>
                )}
              </section>
              <section>
                <h2>建议测试</h2>
                {report.suggested_tests.map((test, i) => (
                  <article className="risk-item" key={i}>
                    <p>{test.text}</p>
                    {test.evidence_ids.map((id) => {
                      const evidence = report.evidence.find((e) => e.evidence_id === id);
                      return evidence ? (
                        <EvidenceLink key={id} item={evidence} onOpen={setLocator} />
                      ) : null;
                    })}
                  </article>
                ))}
              </section>
            </div>
          )}
          {tab === 'evidence' && (
            <div className="report-grid">
              {[
                ['相关测试', report.related_tests],
                ['相关文档', report.related_docs],
                ['配置', report.related_configuration],
                ['全部证据', report.evidence],
              ].map(([label, items]) => (
                <section key={label as string}>
                  <h2>{label as string}</h2>
                  <EvidenceList items={items as ImpactResult['evidence']} onOpen={setLocator} />
                </section>
              ))}
              <section>
                <h2>相关提交</h2>
                {report.related_history.map((commit) => (
                  <div className="commit-row" key={commit.commit_sha}>
                    <code>{short(commit.commit_sha)}</code>
                    <span>{commit.message}</span>
                  </div>
                ))}
              </section>
            </div>
          )}
          {tab === 'unknowns' && (
            <div className="unknowns">
              <Badge tone="amber">证据不足</Badge>
              {report.unknowns.length ? (
                <ul>
                  {report.unknowns.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              ) : (
                <p>当前报告没有额外记录的不确定项。</p>
              )}
            </div>
          )}
          {report.model_answer && <AnswerView answer={report.model_answer} onOpen={setLocator} />}
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
