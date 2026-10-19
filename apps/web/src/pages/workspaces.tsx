import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  Clock3,
  Database,
  FileCode2,
  FolderGit2,
  GitBranch,
  GitCommitHorizontal,
  Play,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api, localDate, short } from '../api';
import {
  Badge,
  Empty,
  ErrorBox,
  Field,
  Loading,
  PageHeading,
  SourceDialog,
  TaskProgress,
  useTask,
} from '../components';
import { useWorkspace } from '../state';
import type { Job, Locator, Workspace, WorkspaceDetail } from '../types';

export function WorkspacesPage() {
  const state = useWorkspace();
  const client = useQueryClient();
  const [path, setPath] = useState('');
  const [locator, setLocator] = useState<Locator | null>(null);
  const [filter, setFilter] = useState('');
  const task = useTask('import');
  const detail = useQuery({
    queryKey: ['workspace', state.workspaceId, state.workspace?.snapshots[0]?.snapshot_id],
    queryFn: () => api<WorkspaceDetail>(`/api/workspaces/${state.workspaceId}`),
    enabled: !!state.workspace,
  });
  const demo = useMutation({
    mutationFn: () =>
      api<{ task: Job; demo: { base: string; head: string; repository: string } }>('/api/demo', {}),
    onSuccess: (data) => {
      task.setTask(data.task);
      setPath(data.demo.repository);
    },
  });
  useEffect(() => {
    if (task.task?.status === 'completed' && task.task.result) {
      const result = task.task.result as { workspace: Workspace };
      state.selectWorkspace(result.workspace.workspace_id);
      void client.invalidateQueries({ queryKey: ['workspaces'] });
    }
  }, [task.task?.id, task.task?.status, client]);
  const snapshot = detail.data?.snapshots[0];
  return (
    <>
      <PageHeading title="仓库工作区" count={`${state.workspaces.length} 个已导入仓库`}>
        <button
          className="button secondary"
          onClick={() => demo.mutate()}
          disabled={demo.isPending || task.pending}
        >
          <Play size={15} />
          打开演示仓库
        </button>
      </PageHeading>
      <form
        className="import-form"
        onSubmit={(e) => {
          e.preventDefault();
          task.start({ action: 'import', repository: path, ref: state.ref });
        }}
      >
        <Field label="本地 Git 仓库路径">
          <input
            aria-label="本地 Git 仓库路径"
            placeholder="D:\projects\my-repository"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            required
            maxLength={4000}
          />
        </Field>
        <button className="button" type="submit" disabled={!path.trim() || task.pending}>
          <Plus size={16} />
          导入仓库
        </button>
      </form>
      <ErrorBox error={task.error || demo.error} />
      <TaskProgress task={task.task} />
      {state.loading ? (
        <Loading />
      ) : !state.workspaces.length ? (
        <Empty>尚未导入仓库。</Empty>
      ) : (
        <section className="repository-list" aria-label="已导入仓库">
          {state.workspaces.map((workspace) => (
            <button
              key={workspace.workspace_id}
              className={`repository-item ${state.workspaceId === workspace.workspace_id ? 'selected' : ''}`}
              onClick={() => state.selectWorkspace(workspace.workspace_id)}
            >
              <FolderGit2 size={24} />
              <div>
                <strong>{workspace.name}</strong>
                <span>{workspace.repository}</span>
              </div>
              <Badge tone="green">已索引</Badge>
              <ArrowRight size={17} />
            </button>
          ))}
        </section>
      )}
      <ErrorBox error={detail.error} />
      {detail.isFetching && <Loading />}
      {detail.data && snapshot && (
        <>
          <div className="section-heading workspace-heading">
            <div>
              <h2>{detail.data.name}</h2>
              <span className="mono muted small">{short(snapshot.commit_sha)}</span>
            </div>
            <button
              className="button secondary"
              disabled={task.pending}
              onClick={() =>
                task.start({
                  action: 'import',
                  repository: detail.data!.repository,
                  ref: state.ref,
                })
              }
            >
              <RefreshCw size={15} />
              更新索引
            </button>
          </div>
          <div className="metrics-strip">
            {[
              { icon: GitBranch, label: '分支', value: detail.data.branches.length },
              {
                icon: GitCommitHorizontal,
                label: '已索引历史提交',
                value: snapshot.stats.history_commits,
              },
              { icon: FileCode2, label: '文件', value: snapshot.stats.inventory_files },
              { icon: Database, label: '证据片段', value: snapshot.stats.chunks },
            ].map(({ icon: Icon, label, value }) => (
              <div className="metric" key={label}>
                <span>
                  <Icon size={15} />
                  {label}
                </span>
                <strong>{value.toLocaleString()}</strong>
              </div>
            ))}
          </div>
          <div className="index-meta">
            <span>
              <Clock3 size={14} />
              {localDate(snapshot.created_at)}
            </span>
            <Badge>{snapshot.stats.index_mode}</Badge>
            <span className="mono small">{snapshot.policy}</span>
          </div>
          <div className="workspace-grid">
            <section>
              <div className="section-heading">
                <h2>提交记录</h2>
                <span className="muted small">最近 100 条</span>
              </div>
              <div className="commit-list">
                {detail.data.history.map((commit) => (
                  <div className="commit-row" key={commit.commit_sha}>
                    <GitCommitHorizontal size={16} />
                    <div>
                      <strong>{commit.message.split('\n')[0]}</strong>
                      <span className="small muted">
                        {commit.author} · {localDate(commit.authored_at)}
                      </span>
                    </div>
                    <button
                      className="text-button mono"
                      title="选择此提交"
                      onClick={() => state.setRef(commit.commit_sha)}
                    >
                      {short(commit.commit_sha)}
                    </button>
                  </div>
                ))}
              </div>
            </section>
            <section>
              <div className="section-heading">
                <h2>文件</h2>
                <span className="muted small">{snapshot.stats.indexed_files} 个可解析文件</span>
              </div>
              <input
                className="file-filter"
                aria-label="筛选文件"
                placeholder="筛选文件路径"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
              <div className="file-list">
                {detail.data.files
                  .filter((file) => file.path.toLowerCase().includes(filter.toLowerCase()))
                  .map((file) => (
                    <button
                      key={file.path}
                      className="file-row"
                      onClick={() =>
                        setLocator({
                          path: file.path,
                          snapshot_id: snapshot.snapshot_id,
                          commit_sha: snapshot.commit_sha,
                        })
                      }
                    >
                      <FileCode2 size={15} />
                      <span>{file.path}</span>
                      <Badge>{file.language || file.status}</Badge>
                    </button>
                  ))}
              </div>
            </section>
          </div>
          <section className="index-diagnostics">
            <h2>索引诊断</h2>
            {snapshot.stats.diagnostics.length ? (
              snapshot.stats.diagnostics.map((entry, i) => (
                <div key={i} className="small mono">
                  {entry.path} · {entry.code}
                </div>
              ))
            ) : (
              <span className="small muted">当前快照没有解析错误。</span>
            )}
          </section>
          <div className="actions">
            <Link className="button secondary" to="/analysis">
              分析变更
              <ArrowRight size={15} />
            </Link>
            <Link className="button secondary" to="/search">
              检索与问答
              <ArrowRight size={15} />
            </Link>
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
