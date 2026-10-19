import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Download,
  FileCode2,
  Loader2,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api, short, submitTask } from './api';
import { useWorkspace } from './state';
import type { Answer, Evidence, Job, Locator, TaskInput } from './types';

const CodeEditor = lazy(() =>
  import('./editors').then((module) => ({ default: module.CodeEditor })),
);
const CodeDiff = lazy(() => import('./editors').then((module) => ({ default: module.CodeDiff })));

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <FileCode2 size={28} strokeWidth={1.4} />
      <p>{children}</p>
    </div>
  );
}
export function ErrorBox({ error }: { error?: Error | string | null }) {
  return error ? (
    <div className="error" role="alert">
      <AlertCircle size={17} />
      <span>{typeof error === 'string' ? error : error.message}</span>
    </div>
  ) : null;
}
export function Loading({ text = '读取中' }: { text?: string }) {
  return (
    <div className="loading">
      <Loader2 size={17} className="spin" />
      {text}
    </div>
  );
}
export function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function PageHeading({
  title,
  count,
  children,
}: {
  title: string;
  count?: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <h1>{title}</h1>
        {count && <span className="muted">{count}</span>}
      </div>
      <div className="actions">{children}</div>
    </header>
  );
}
export function RequireWorkspace({ children }: { children: ReactNode }) {
  const { workspace } = useWorkspace();
  return workspace ? (
    children
  ) : (
    <Empty>
      请先在<Link to="/">仓库工作区</Link>导入并选择仓库。
    </Empty>
  );
}
export function useTask(page: string) {
  const { jobs, workspaceId, rememberJob } = useWorkspace();
  const [localId, setLocalId] = useState('');
  const id = page === 'import' ? localId : jobs[`${workspaceId}:${page}`];
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: submitTask,
    onSuccess: (task) => {
      setLocalId(task.id);
      rememberJob(page, task.id);
      client.setQueryData(['task', task.id], task);
      void client.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
  const query = useQuery({
    queryKey: ['task', id],
    queryFn: () => api<Job>(`/api/tasks/${id}`),
    enabled: !!id,
    refetchInterval: (q) =>
      q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 2000 : false,
  });
  useEffect(() => {
    if (!id || !query.data || !['queued', 'running'].includes(query.data.status)) return;
    const stream = new EventSource(`/api/tasks/${id}/events`);
    stream.addEventListener('progress', () => {
      void client.invalidateQueries({ queryKey: ['task', id] });
    });
    stream.addEventListener('finished', () => {
      stream.close();
      void client.invalidateQueries({ queryKey: ['task', id] });
      void client.invalidateQueries({ queryKey: ['workspaces'] });
      void client.invalidateQueries({ queryKey: ['tasks'] });
    });
    return () => stream.close();
  }, [id, query.data?.status, client]);
  return {
    task: query.data,
    start: (input: TaskInput) => mutation.mutate(input),
    createdId: mutation.data?.id,
    pending:
      mutation.isPending || (!!query.data && ['queued', 'running'].includes(query.data.status)),
    error: mutation.error || query.error,
    setTask: (task: Job) => {
      setLocalId(task.id);
      client.setQueryData(['task', task.id], task);
      rememberJob(page, task.id);
    },
  };
}
const phases: Record<string, string> = {
  queue: '等待执行',
  analysis: '分析中',
  index: '建立索引',
  version: '固定版本',
  prepare: '准备快照',
  baseline: '规则报告',
  tool: '调用工具',
  agent_plan: '规划步骤',
  agent_answer: '生成回答',
  answer_validation: '校验引用',
  diff_validation: '校验 diff',
  task: '任务',
  stop: '停止',
};
export function TaskProgress({ task }: { task?: Job }) {
  if (!task) return null;
  const active = ['queued', 'running'].includes(task.status);
  const event = task.events.at(-1)?.data;
  return (
    <>
      <div
        className={`task-progress ${active ? 'active' : task.status === 'failed' ? 'failed' : ''}`}
        role="status"
      >
        {active ? (
          <Loader2 size={16} className="spin" />
        ) : task.status === 'failed' ? (
          <AlertCircle size={16} />
        ) : (
          <CheckCircle2 size={16} />
        )}
        <span>
          {task.status === 'failed'
            ? '任务失败'
            : active
              ? phases[event?.state || ''] || '分析中'
              : '任务完成'}
        </span>
        <span className="muted">
          {task.events.length} 个事件
          {task.duration_ms > 0 ? ` · ${(task.duration_ms / 1000).toFixed(1)}s` : ''}
        </span>
        <Link to={`/traces/${task.id}`}>
          查看过程
          <ChevronRight size={13} />
        </Link>
      </div>
      <ErrorBox error={task.error} />
    </>
  );
}
export function ExportButtons({ task, markdown = false }: { task?: Job; markdown?: boolean }) {
  if (!task?.result) return null;
  return (
    <>
      {(markdown ? ['markdown', 'json'] : ['json']).map((format) => (
        <a
          className="button secondary"
          key={format}
          href={`/api/tasks/${task.id}/export?format=${format}`}
          download
        >
          <Download size={15} />
          {format === 'markdown' ? 'Markdown' : 'JSON'}
        </a>
      ))}
    </>
  );
}
export function EvidenceLink({
  item,
  onOpen,
  children,
}: {
  item: Locator;
  onOpen: (item: Locator) => void;
  children?: ReactNode;
}) {
  return (
    <button
      className="text-button evidence-link"
      onClick={() => onOpen(item)}
      title={`${item.path}:${item.line_start || 1}`}
    >
      <FileCode2 size={14} />
      <span>{children || `${item.path}${item.line_start ? `:${item.line_start}` : ''}`}</span>
    </button>
  );
}
export function EvidenceList({
  items,
  onOpen,
}: {
  items: Evidence[];
  onOpen: (item: Locator) => void;
}) {
  return items.length ? (
    <div className="evidence-list">
      {items.map((item, i) => (
        <div className="evidence-row" key={`${item.evidence_id}-${i}`}>
          <span className="rank">{i + 1}</span>
          <div>
            <EvidenceLink item={item} onOpen={onOpen} />
            <div className="muted small">
              {item.symbol || item.kind || '文件'} · {short(item.commit_sha)}
            </div>
          </div>
          <span className="score">
            {(
              item.graph_score ??
              item.hybrid_score ??
              item.rerank_score ??
              item.vector_score ??
              item.bm25_score
            )?.toFixed(5) || '-'}
          </span>
        </div>
      ))}
    </div>
  ) : (
    <Empty>没有检索到相关证据。</Empty>
  );
}
export function AnswerView({
  answer,
  onOpen,
}: {
  answer: Answer;
  onOpen: (item: Locator) => void;
}) {
  return (
    <div className="answer">
      <div className="section-heading">
        <h2>回答</h2>
        <Badge tone={answer.status === 'answered' ? 'green' : 'amber'}>
          {answer.status === 'answered' ? '引用已校验' : '证据不足'}
        </Badge>
      </div>
      <p className="answer-summary">{answer.summary}</p>
      {answer.claims.map((claim, i) => (
        <div className="claim" key={i}>
          <p>{claim.text}</p>
          <div className="actions">
            {claim.citation_ids.map((id) => {
              const citation = answer.citations.find((c) => c.citation_id === id);
              return citation ? (
                <EvidenceLink key={id} item={citation} onOpen={onOpen}>
                  {id} · {citation.path}:{citation.line_start}
                </EvidenceLink>
              ) : null;
            })}
          </div>
        </div>
      ))}
      {answer.unknowns.length > 0 && (
        <div className="unknowns">
          <h3>证据不足</h3>
          <ul>
            {answer.unknowns.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="small muted">
        {answer.provider} / {answer.model}
      </div>
    </div>
  );
}
export function SourceDialog({
  locator,
  onClose,
  workspaceId,
}: {
  locator: Locator | null;
  onClose: () => void;
  workspaceId: string;
}) {
  const query = useQuery({
    queryKey: ['source', workspaceId, locator?.snapshot_id, locator?.path, locator?.evidence_id],
    queryFn: () =>
      api<{ text: string; commit_sha: string; evidence: Evidence | null }>('/api/source', {
        workspace_id: workspaceId,
        snapshot_id: locator!.snapshot_id,
        path: locator!.path,
        evidence_id: locator!.evidence_id || '',
      }),
    enabled: !!locator,
  });
  useEffect(() => {
    if (!locator) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [locator, onClose]);
  if (!locator) return null;
  return (
    <div
      className="modal-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="source-dialog" role="dialog" aria-modal="true" aria-label="代码证据">
        <header>
          <div>
            <strong>{locator.path}</strong>
            <div className="small muted">
              commit {short(query.data?.commit_sha || locator.commit_sha)} · L
              {locator.line_start || 1}
              {locator.line_end ? `–${locator.line_end}` : ''}
            </div>
          </div>
          <button
            className="icon-button"
            title="关闭代码"
            aria-label="关闭代码"
            onClick={onClose}
            autoFocus
          >
            <X size={19} />
          </button>
        </header>
        <ErrorBox error={query.error} />
        {query.isPending ? (
          <Loading />
        ) : (
          query.data && (
            <Suspense fallback={<Loading text="加载代码" />}>
              <CodeEditor locator={locator} text={query.data.text} />
            </Suspense>
          )
        )}
      </section>
    </div>
  );
}
export function DiffView({
  workspaceId,
  base,
  head,
  path,
}: {
  workspaceId: string;
  base: string;
  head: string;
  path: string;
}) {
  const query = useQuery({
    queryKey: ['diff', workspaceId, base, head, path],
    queryFn: () =>
      api<{
        path: string;
        base: { text: string; commit_sha: string };
        head: { text: string; commit_sha: string };
      }>('/api/diff', {
        workspace_id: workspaceId,
        base_snapshot_id: base,
        head_snapshot_id: head,
        path,
      }),
    enabled: !!path,
  });
  if (!path) return <Empty>选择变更文件查看 diff。</Empty>;
  return (
    <>
      <div className="diff-heading">
        <strong>{path}</strong>
        <span className="small muted">
          {short(query.data?.base.commit_sha)} → {short(query.data?.head.commit_sha)}
        </span>
      </div>
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        query.data && (
          <div className="diff-editor">
            <Suspense fallback={<Loading text="加载 diff" />}>
              <CodeDiff path={path} before={query.data.base.text} after={query.data.head.text} />
            </Suspense>
          </div>
        )
      )}
    </>
  );
}
