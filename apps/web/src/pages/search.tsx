import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Play, Search } from 'lucide-react';
import {
  AnswerView,
  Badge,
  Empty,
  ErrorBox,
  EvidenceList,
  ExportButtons,
  Field,
  PageHeading,
  RequireWorkspace,
  SourceDialog,
  TaskProgress,
  useTask,
} from '../components';
import { useWorkspace } from '../state';
import type { AskResult, Locator, SearchResult, Strategy } from '../types';

export default function SearchPage() {
  return (
    <>
      <PageHeading title="检索与问答" />
      <RequireWorkspace>
        <SearchWorkspace />
      </RequireWorkspace>
    </>
  );
}
function SearchWorkspace() {
  const state = useWorkspace();
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get('question') || '');
  const strategies: Strategy[] = ['keyword', 'vector', 'hybrid', 'graph'];
  const [strategy, setStrategy] = useState<Strategy>(
    strategies.find((value) => value === params.get('retrieval')) || 'hybrid',
  );
  const [path, setPath] = useState('');
  const [mode, setMode] = useState<'search' | 'ask'>(
    params.get('mode') === 'search' ? 'search' : 'ask',
  );
  const [locator, setLocator] = useState<Locator | null>(null);
  const task = useTask('search');
  const result = task.task?.result as AskResult | SearchResult | undefined;
  const answer = result && 'answer' in result ? result : undefined;
  const items = result
    ? 'results' in result
      ? result.results
      : result.retrieval.map((item) => ({ ...item, snapshot_id: result.snapshot_id }))
    : [];
  return (
    <>
      <form
        className="query-form"
        onSubmit={(e) => {
          e.preventDefault();
          task.start(
            mode === 'ask'
              ? {
                  action: 'ask',
                  workspace_id: state.workspaceId,
                  ref: state.ref,
                  question: query,
                  retrieval: strategy,
                  provider: state.provider,
                  max_follow_ups: 1,
                }
              : {
                  action: 'search',
                  workspace_id: state.workspaceId,
                  ref: state.ref,
                  query,
                  retrieval: strategy,
                  limit: 10,
                  path_prefix: path,
                },
          );
        }}
      >
        <div className="section-heading">
          <div className="segmented" role="group" aria-label="检索模式">
            {[
              ['ask', '问答'],
              ['search', '检索'],
            ].map(([value, label]) => (
              <button
                type="button"
                className={mode === value ? 'active' : ''}
                key={value}
                onClick={() => setMode(value as 'ask' | 'search')}
              >
                {label}
              </button>
            ))}
          </div>
          <Badge>{mode === 'ask' ? state.provider : '仅检索'}</Badge>
        </div>
        <Field label="问题">
          <textarea
            aria-label="问题"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="例如：TaskService.create_task 如何处理任务标题？"
            required
            maxLength={4000}
          />
        </Field>
        <div className="query-options">
          <Field label="检索策略">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value as Strategy)}>
              <option value="hybrid">Hybrid · 混合</option>
              <option value="keyword">Keyword · 关键词</option>
              <option value="vector">Vector · 向量</option>
              <option value="graph">Graph · 图增强</option>
            </select>
          </Field>
          {mode === 'search' && (
            <Field label="路径前缀">
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="src/" />
            </Field>
          )}
          <button className="button" disabled={task.pending || !query.trim()}>
            {mode === 'ask' ? <Play size={15} /> : <Search size={15} />}
            {mode === 'ask' ? '提问' : '检索'}
          </button>
        </div>
      </form>
      <ErrorBox error={task.error} />
      <TaskProgress task={task.task} />
      {result ? (
        <>
          <div className="section-heading">
            <div className="actions">
              <Badge tone="green">已确认 · 版本定位</Badge>
              <code className="small">
                {('workflow' in result ? result.workflow.commit_sha : result.commit_sha).slice(
                  0,
                  12,
                )}
              </code>
            </div>
            <ExportButtons task={task.task} />
          </div>
          <div className="search-results">
            <section>
              {answer ? (
                <AnswerView answer={answer.answer} onOpen={setLocator} />
              ) : (
                <>
                  <h2>检索结果</h2>
                  <EvidenceList items={items} onOpen={setLocator} />
                </>
              )}
            </section>
            {answer && (
              <section className="retrieval-pane">
                <div className="section-heading">
                  <h2>检索证据</h2>
                  <span className="small muted">排序分数</span>
                </div>
                <EvidenceList items={items} onOpen={setLocator} />
                <div className="telemetry small muted">
                  耗时 {answer.telemetry.duration_ms} ms ·{' '}
                  {Object.entries(answer.telemetry.usage)
                    .map(([key, value]) => `${key}: ${value}`)
                    .join(' · ') || '供应商未返回 token 用量'}
                </div>
              </section>
            )}
          </div>
        </>
      ) : (
        <Empty>输入问题开始检索。</Empty>
      )}
      <SourceDialog
        locator={locator}
        onClose={() => setLocator(null)}
        workspaceId={state.workspaceId}
      />
    </>
  );
}
