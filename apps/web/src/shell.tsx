import { lazy, Suspense, useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Blocks,
  BookOpen,
  FlaskConical,
  FolderGit2,
  GitBranch,
  GitCompareArrows,
  Menu,
  Network,
  Settings2,
  Workflow,
  X,
} from 'lucide-react';
import { api } from './api';
import { Badge, ErrorBox, Field, Loading } from './components';
import { useWorkspace } from './state';
import type { Provider } from './types';
import { WorkspacesPage } from './pages/workspaces';
const AnalysisPage = lazy(() => import('./pages/analysis'));
const GraphPage = lazy(() => import('./pages/graph'));
const SearchPage = lazy(() => import('./pages/search'));
const TracePage = lazy(() => import('./pages/trace'));
const EvaluationPage = lazy(() => import('./pages/evaluation'));

const navigation = [
  { to: '/', label: '仓库工作区', icon: FolderGit2 },
  { to: '/analysis', label: '变更分析', icon: GitCompareArrows },
  { to: '/graph', label: '代码关系图', icon: Network },
  { to: '/search', label: '检索与问答', icon: BookOpen },
  { to: '/traces', label: 'Trace 调试', icon: Workflow },
  { to: '/evaluations', label: '评测对比', icon: FlaskConical },
];
export function App() {
  const state = useWorkspace();
  const [settings, setSettings] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [key, setKey] = useState('');
  const [saved, setSaved] = useState(false);
  const client = useQueryClient();
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ version: string; key_configured: boolean }>('/api/health'),
  });
  const saveKey = useMutation({
    mutationFn: () => api('/api/settings', { api_key: key }),
    onSuccess: () => {
      setKey('');
      setSaved(true);
      void client.invalidateQueries({ queryKey: ['health'] });
    },
  });
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenu ? 'mobile-open' : ''}`}>
        <div className="brand">
          <span className="brand-mark">
            <Blocks size={22} />
          </span>
          <div>
            RepoLens<span>代码分析工作台</span>
          </div>
          <button
            className="icon-button mobile-only"
            title="收起导航"
            onClick={() => setMobileMenu(false)}
          >
            <X size={20} />
          </button>
        </div>
        <div className="sidebar-label">工作空间</div>
        <nav aria-label="主导航">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink
              to={to}
              end={to === '/'}
              key={to}
              onClick={() => setMobileMenu(false)}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <i />
            本地工作区 <Badge>V6</Badge>
          </div>
          <button
            className="nav-link"
            onClick={() => {
              setSettings(true);
              setSaved(false);
            }}
          >
            <Settings2 size={18} />
            模型设置
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-only"
            title="打开导航"
            aria-label="打开导航"
            onClick={() => setMobileMenu(!mobileMenu)}
          >
            <Menu size={20} />
          </button>
          <div className="workspace-switch">
            <FolderGit2 size={17} />
            <select
              aria-label="当前仓库"
              value={state.workspaceId}
              onChange={(e) => state.selectWorkspace(e.target.value)}
            >
              <option value="">选择仓库</option>
              {state.workspaces.map((w) => (
                <option key={w.workspace_id} value={w.workspace_id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <div className="ref-control">
            <GitBranch size={15} />
            <input
              aria-label="当前 Git ref"
              value={state.ref}
              onChange={(e) => state.setRef(e.target.value)}
            />
          </div>
          <div className="topbar-right">
            <Badge tone={health.data ? 'green' : 'amber'}>
              {health.data ? '服务在线' : '连接中'}
            </Badge>
            <button
              className="icon-button"
              title="模型设置"
              aria-label="模型设置"
              onClick={() => {
                setSettings(true);
                setSaved(false);
              }}
            >
              <Settings2 size={18} />
            </button>
          </div>
        </header>
        <main>
          <ErrorBox error={health.error || state.error} />
          <Suspense fallback={<Loading text="加载页面" />}>
            <Routes>
              <Route path="/" element={<WorkspacesPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              <Route path="/graph" element={<GraphPage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/traces" element={<TracePage />} />
              <Route path="/traces/:taskId" element={<TracePage />} />
              <Route path="/evaluations" element={<EvaluationPage />} />
              <Route path="*" element={<div className="empty">页面不存在。</div>} />
            </Routes>
          </Suspense>
        </main>
        <footer className="app-footer">
          <span>
            RepoLens <span className="muted">/</span> {state.workspace?.name || '工作区'}
          </span>
          <span>本地 Git · {health.data?.version || '…'}</span>
        </footer>
      </div>
      {settings && (
        <div className="modal-backdrop">
          <section
            className="settings-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="模型设置"
          >
            <div className="section-heading">
              <h2>模型设置</h2>
              <button
                className="icon-button"
                title="关闭设置"
                aria-label="关闭设置"
                onClick={() => {
                  setSettings(false);
                  setKey('');
                }}
              >
                <X size={18} />
              </button>
            </div>
            <Field label="回答模型">
              <select
                value={state.provider}
                onChange={(e) => state.setProvider(e.target.value as Provider)}
              >
                <option value="mock">Mock · 离线演示</option>
                <option value="deepseek">DeepSeek</option>
                <option value="langchain">LangChain + DeepSeek</option>
              </select>
            </Field>
            <Field label="DeepSeek API Key">
              <input
                type="password"
                autoComplete="off"
                value={key}
                onChange={(e) => {
                  setKey(e.target.value);
                  setSaved(false);
                }}
                placeholder={health.data?.key_configured ? '已配置；留空保存可清除' : '尚未配置'}
              />
            </Field>
            <p className="small muted">
              密钥只保留在当前服务内存中，关闭服务后失效。两种 DeepSeek
              连接方式都会发送本次分析所需的代码证据。
            </p>
            <ErrorBox error={saveKey.error} />
            {saved && <Badge tone="green">已更新密钥配置</Badge>}
            <div className="actions end">
              <button
                className="button"
                onClick={() => saveKey.mutate()}
                disabled={saveKey.isPending}
              >
                保存密钥
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
