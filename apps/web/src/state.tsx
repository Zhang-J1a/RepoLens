import { createContext, useContext, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import type { Provider, Workspace } from './types';

type Context = {
  workspaces: Workspace[];
  workspace?: Workspace;
  workspaceId: string;
  selectWorkspace: (id: string) => void;
  ref: string;
  setRef: (ref: string) => void;
  provider: Provider;
  setProvider: (provider: Provider) => void;
  jobs: Record<string, string>;
  rememberJob: (page: string, id: string) => void;
  loading: boolean;
  error: Error | null;
};
const State = createContext<Context | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => api<Workspace[]>('/api/workspaces'),
  });
  const [workspaceId, setWorkspaceId] = useState(
    () => localStorage.getItem('repolens.workspace.v5') || '',
  );
  const [ref, setRef] = useState('HEAD');
  const [provider, setProvider] = useState<Provider>('mock');
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const workspaces = query.data || [];
  const selectWorkspace = (id: string) => {
    setWorkspaceId(id);
    setRef('HEAD');
    localStorage.setItem('repolens.workspace.v5', id);
  };
  return (
    <State.Provider
      value={{
        workspaces,
        workspaceId,
        workspace: workspaces.find((w) => w.workspace_id === workspaceId),
        selectWorkspace,
        ref,
        setRef,
        provider,
        setProvider,
        jobs,
        rememberJob: (page, id) =>
          setJobs((previous) => ({ ...previous, [`${workspaceId}:${page}`]: id })),
        loading: query.isPending,
        error: query.error,
      }}
    >
      {children}
    </State.Provider>
  );
}
export function useWorkspace() {
  const state = useContext(State);
  if (!state) throw new Error('Workspace context');
  return state;
}
