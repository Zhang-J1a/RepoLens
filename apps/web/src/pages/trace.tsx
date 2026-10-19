import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, CheckCircle2, ChevronRight, Play, Workflow } from 'lucide-react';
import { api, localDate, short } from '../api';
import {
  AnswerView,
  Badge,
  Empty,
  ErrorBox,
  ExportButtons,
  Field,
  Loading,
  PageHeading,
  SourceDialog,
  TaskProgress,
  useTask,
} from '../components';
import { useWorkspace } from '../state';
import type { AgentResult, Job, Locator, TraceEvent } from '../types';

export default function TracePage() {
  const state = useWorkspace();
  const { taskId } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [question, setQuestion] = useState('');
  const [base, setBase] = useState('');
  const [steps, setSteps] = useState(8);
  const [timeout, setTimeout] = useState(120);
  const [locator, setLocator] = useState<Locator | null>(null);
  const [failedOnly, setFailedOnly] = useState(false);
  const runner = useTask('agent');
  const list = useQuery({
    queryKey: ['tasks'],
    queryFn: () => api<Job[]>('/api/tasks'),
    refetchInterval: 5000,
  });
  const task = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => api<Job>(`/api/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (q) =>
      q.state.data && ['running', 'queued'].includes(q.state.data.status) ? 1000 : false,
  });
  useEffect(() => {
    if (runner.createdId) navigate(`/traces/${runner.createdId}`);
  }, [runner.createdId]);
  useEffect(() => {
    if (!taskId || !task.data || !['running', 'queued'].includes(task.data.status)) return;
    const stream = new EventSource(`/api/tasks/${taskId}/events`);
    stream.addEventListener('progress', () => {
      void client.invalidateQueries({ queryKey: ['task', taskId] });
    });
    stream.addEventListener('finished', () => {
      stream.close();
      void client.invalidateQueries({ queryKey: ['task', taskId] });
      void client.invalidateQueries({ queryKey: ['tasks'] });
    });
    return () => stream.close();
  }, [taskId, task.data?.status, client]);
  const agent =
    task.data?.action === 'agent' ? (task.data.result as AgentResult | undefined) : undefined;
  const usage = agent?.trace.consumed.provider_usage;
  const tokens =
    usage?.total_tokens ?? (usage?.prompt_tokens || 0) + (usage?.completion_tokens || 0);
  const events: TraceEvent[] =
    agent?.trace.events ||
    task.data?.events.map((event) => ({
      sequence: event.id,
      state: event.data.state || '',
      status: event.data.status || '',
      name: event.data.name,
      input: event.data.input || {},
      output: event.data.output || {},
      elapsed_ms: event.data.elapsed_ms || 0,
      error_code: event.data.error_code || event.data.error,
    })) ||
    [];
  return (
    <>
      <PageHeading title="Trace 调试" count={`${list.data?.length || 0} 个当前服务任务`} />
      {state.workspace && (
        <form
          className="agent-form"
          onSubmit={(e) => {
            e.preventDefault();
            runner.start({
              action: 'agent',
              workspace_id: state.workspaceId,
              ref: state.ref,
              question,
              base,
              provider: state.provider,
              max_steps: steps,
              timeout_seconds: timeout,
            });
          }}
        >
          <Field label="Agent 分析问题">
            <input
              aria-label="Agent 分析问题"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              required
              placeholder="TaskService.create_task 的调用方和相关测试有哪些？"
              maxLength={4000}
            />
          </Field>
          <div className="agent-options">
            <Field label="Base（可选）">
              <input value={base} onChange={(e) => setBase(e.target.value)} placeholder="HEAD~1" />
            </Field>
            <Field label="最大步数">
              <input
                type="number"
                min={1}
                max={32}
                value={steps}
                onChange={(e) => setSteps(Number(e.target.value))}
              />
            </Field>
            <Field label="超时（秒）">
              <input
                type="number"
                min={1}
                max={600}
                value={timeout}
                onChange={(e) => setTimeout(Number(e.target.value))}
              />
            </Field>
            <button className="button" disabled={runner.pending}>
              <Play size={15} />
              运行 Agent
            </button>
          </div>
        </form>
      )}
      <ErrorBox error={runner.error || list.error || task.error} />
      <div className="trace-layout">
        <aside className="task-list">
          {list.isPending ? (
            <Loading />
          ) : list.data?.length ? (
            list.data.map((item) => (
              <Link
                className={`task-item ${taskId === item.id ? 'selected' : ''}`}
                key={item.id}
                to={`/traces/${item.id}`}
              >
                <Workflow size={17} />
                <div>
                  <strong>
                    {item.action}
                    <Badge
                      tone={
                        item.status === 'failed'
                          ? 'red'
                          : item.status === 'completed'
                            ? 'green'
                            : ''
                      }
                    >
                      {item.status}
                    </Badge>
                  </strong>
                  <span>
                    {short(item.id)} · {localDate(item.created_at)}
                  </span>
                </div>
                <ChevronRight size={14} />
              </Link>
            ))
          ) : (
            <Empty>还没有分析任务。</Empty>
          )}
        </aside>
        <section className="trace-content">
          {!taskId ? (
            <Empty>选择一次任务查看执行过程。</Empty>
          ) : task.data ? (
            <>
              <div className="section-heading">
                <h2>
                  {task.data.action} <code className="small">{short(task.data.id)}</code>
                </h2>
                <div className="actions">
                  <ExportButtons task={task.data} markdown={!!agent?.rule_report} />
                </div>
              </div>
              <TaskProgress task={task.data} />
              {agent && (
                <>
                  <div className="trace-ids mono small">
                    task {agent.trace.task_id}
                    <br />
                    trace {agent.trace.trace_id}
                  </div>
                  <div className="metrics-strip">
                    <div className="metric">
                      <span>工具步数</span>
                      <strong>
                        {agent.trace.consumed.steps} / {agent.trace.budget.max_steps}
                      </strong>
                    </div>
                    <div className="metric">
                      <span>模型调用</span>
                      <strong>{agent.trace.consumed.model_calls}</strong>
                    </div>
                    <div className="metric">
                      <span>Token 用量</span>
                      <strong>{tokens || '未返回'}</strong>
                    </div>
                  </div>
                  <div className="actions">
                    <Badge tone={agent.status === 'degraded' ? 'amber' : 'green'}>
                      {agent.status === 'degraded' ? '已降级' : '已完成'}
                    </Badge>
                    <code className="small">{agent.stop_reason}</code>
                  </div>
                </>
              )}
              <div className="section-heading">
                <h2>执行步骤</h2>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={failedOnly}
                    onChange={(e) => setFailedOnly(e.target.checked)}
                  />
                  仅失败步骤
                </label>
              </div>
              <div className="trace-events">
                {events
                  .filter(
                    (event) =>
                      !failedOnly ||
                      ['error', 'denied', 'failed', 'degraded'].includes(event.status),
                  )
                  .map((event) => (
                    <details className={`trace-event ${event.status}`} key={event.sequence}>
                      <summary>
                        <span className="event-number">{event.sequence}</span>
                        {['error', 'denied', 'failed'].includes(event.status) ? (
                          <AlertCircle size={16} />
                        ) : (
                          <CheckCircle2 size={16} />
                        )}
                        <strong>{event.name || event.state}</strong>
                        <Badge>{event.status}</Badge>
                        <span className="small muted">{event.elapsed_ms} ms</span>
                      </summary>
                      <div className="event-body">
                        <h3>输入</h3>
                        <pre>{JSON.stringify(event.input, null, 2)}</pre>
                        <h3>输出</h3>
                        <pre>{JSON.stringify(event.output, null, 2)}</pre>
                        {event.error_code && <ErrorBox error={event.error_code} />}
                      </div>
                    </details>
                  ))}
              </div>
              {agent && (
                <>
                  <AnswerView answer={agent.answer} onOpen={setLocator} />
                  {agent.rule_report && (
                    <div className="unknowns">
                      <h3>保留的规则报告</h3>
                      <p>{agent.rule_report.summary}</p>
                      <ExportButtons task={task.data} markdown />
                    </div>
                  )}
                </>
              )}
            </>
          ) : task.isPending ? (
            <Loading />
          ) : null}
        </section>
      </div>
      <SourceDialog
        locator={locator}
        onClose={() => setLocator(null)}
        workspaceId={task.data?.workspace_id || state.workspaceId}
      />
    </>
  );
}
