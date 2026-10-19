import type { components } from './api-schema';

export type TaskInput =
  | components['schemas']['ImportInput']
  | components['schemas']['AskInput']
  | components['schemas']['SearchInput']
  | components['schemas']['ImpactInput']
  | components['schemas']['GraphInput']
  | components['schemas']['AgentInput'];
export type Strategy = 'keyword' | 'vector' | 'hybrid' | 'graph';
export type Provider = 'mock' | 'deepseek' | 'langchain';
export interface Snapshot {
  snapshot_id: string;
  repository_id: string;
  root: string;
  commit_sha: string;
  policy: string;
  created_at: string;
  stats: {
    inventory_files: number;
    indexed_files: number;
    symbols: number;
    chunks: number;
    history_commits: number;
    index_mode: string;
    diagnostics: { path: string; code: string }[];
  };
}
export interface Workspace {
  workspace_id: string;
  name: string;
  repository: string;
  snapshots: Snapshot[];
}
export interface WorkspaceDetail extends Workspace {
  branches: string[];
  history: { commit_sha: string; message: string; author: string; authored_at: string }[];
  files: { path: string; language: string | null; status: string }[];
}
export interface Locator {
  evidence_id?: string | null;
  snapshot_id: string;
  commit_sha: string;
  path: string;
  symbol?: string | null;
  line_start?: number | null;
  line_end?: number | null;
}
export interface Evidence extends Locator {
  kind?: string;
  text?: string;
  bm25_score?: number;
  vector_score?: number;
  hybrid_score?: number;
  graph_score?: number;
  rerank_score?: number;
  retrieval_method?: string;
}
export interface Answer {
  status: 'answered' | 'abstained';
  summary: string;
  provider: string;
  model: string;
  claims: { text: string; citation_ids: string[] }[];
  citations: (Locator & { citation_id: string })[];
  unknowns: string[];
}
export interface AskResult {
  answer: Answer;
  retrieval: Evidence[];
  snapshot_id: string;
  telemetry: { duration_ms: number; usage: Record<string, number>; trace_id: string };
  workflow: { commit_sha: string; snapshot_id: string };
}
export interface SearchResult {
  results: Evidence[];
  snapshot_id: string;
  commit_sha: string;
  strategy: string;
}
export interface ChangedFile {
  path: string;
  status: string;
  category: string;
  symbols: { name: string; change: string; evidence_id?: string; evidence_snapshot_id?: string }[];
}
export interface ImpactResult {
  schema_version: string;
  summary: string;
  status: string;
  trace_id: string;
  base: { snapshot_id: string; commit_sha: string };
  head: { snapshot_id: string; commit_sha: string };
  changed_files: ChangedFile[];
  evidence: Evidence[];
  related_tests: Evidence[];
  related_docs: Evidence[];
  related_configuration: Evidence[];
  related_callers: Evidence[];
  related_callees: Evidence[];
  related_history: { commit_sha: string; message: string }[];
  risks: {
    severity: string;
    reason: string;
    inference: boolean;
    evidence_ids: string[];
    path: string;
  }[];
  suggested_tests: { text: string; evidence_ids: string[] }[];
  unknowns: string[];
  model_answer?: Answer;
}
export interface GraphNode extends Locator {
  id: string;
  kind: string;
  name: string;
  distance: number;
  provenance: Record<string, unknown> & { commit_sha: string };
}
export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  kind: string;
  inference: boolean;
  evidence_id?: string;
  provenance: Locator;
}
export interface GraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  snapshot_id: string;
  commit_sha: string;
  seed_node_ids: string[];
  truncated: boolean;
  ambiguous_seed: boolean;
  base_graph?: GraphResult;
  stats: Record<string, unknown>;
}
export interface TraceEvent {
  sequence: number;
  state: string;
  name?: string;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  elapsed_ms: number;
  error_code?: string;
}
export interface AgentResult {
  status: string;
  stop_reason: string;
  answer: Answer;
  rule_report?: ImpactResult;
  workflow: { commit_sha: string };
  evidence: Evidence[];
  trace: {
    task_id: string;
    trace_id: string;
    events: TraceEvent[];
    budget: Record<string, number>;
    consumed: {
      steps: number;
      model_calls: number;
      duration_ms: number;
      provider_usage: Record<string, number>;
    };
  };
}
export interface ProgressEvent {
  id: number;
  timestamp: string;
  data: Partial<TraceEvent> & { error?: string };
}
export interface Job {
  id: string;
  action: string;
  workspace_id?: string | null;
  status: 'queued' | 'running' | 'completed' | 'failed';
  created_at: string;
  duration_ms: number;
  events: ProgressEvent[];
  error?: string | null;
  result: unknown;
  request_id: string;
  error_code?: string | null;
}
export interface Evaluation {
  id: string;
  group: string;
  citation_precision: number | null;
  answer_accuracy: number | null;
  run: {
    strategy: string;
    dataset: string;
    dataset_sha256: string;
    commit_sha: string;
    retrieval: string;
    query_policy: string;
    index_policy: string;
    bm25_weights: Record<string, number>;
    rerank_weights: Record<string, number>;
    started_at_utc: string;
    top_k: number;
  };
  metrics: Record<string, number> & { latency_ms: { p50: number; p95: number; mean: number } };
  cases: {
    id: string;
    category: string;
    query: string;
    'recall@10': number;
    mrr: number;
    latency_ms: number;
    retrieved_evidence?: Evidence[];
    expected_evidence: { path: string; symbol?: string; line_start: number; line_end: number }[];
  }[];
}
