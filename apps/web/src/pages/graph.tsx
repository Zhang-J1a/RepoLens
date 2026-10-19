import { useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  MarkerType,
  useNodesState,
  type Node,
  type Edge,
} from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import { Expand, Network, Play } from 'lucide-react';
import {
  Badge,
  Empty,
  ErrorBox,
  EvidenceLink,
  Field,
  PageHeading,
  RequireWorkspace,
  SourceDialog,
  TaskProgress,
  useTask,
} from '../components';
import { useWorkspace } from '../state';
import type { GraphEdge, GraphNode, GraphResult, Locator } from '../types';
import { short } from '../api';

const colors: Record<string, string> = {
  function: '#087f73',
  class: '#9b4bb5',
  test: '#bb7419',
  module: '#3978b4',
  file: '#667084',
  document: '#b64b70',
  configuration: '#ad6a2a',
  commit: '#586878',
  repository: '#526372',
  branch: '#526372',
};
const nodeNames: Record<string, string> = {
  function: '函数',
  class: '类',
  test: '测试',
  module: '模块',
  file: '文件',
  document: '文档',
  configuration: '配置',
  commit: '提交',
  repository: '仓库',
  branch: '分支',
};
function GraphCanvas({
  nodes,
  edges,
  seeds,
  onNode,
  onEdge,
}: {
  nodes: Node[];
  edges: Edge[];
  seeds: string[];
  onNode: (id: string) => void;
  onEdge: (id: string) => void;
}) {
  const [displayNodes, setNodes, onNodesChange] = useNodesState(nodes);
  useEffect(
    () =>
      setNodes((previous) =>
        nodes.map((node) => ({
          ...node,
          position: previous.find((old) => old.id === node.id)?.position || node.position,
        })),
      ),
    [nodes, setNodes],
  );
  return (
    <ReactFlow
      nodes={displayNodes}
      edges={edges}
      onNodesChange={onNodesChange}
      minZoom={0.08}
      maxZoom={2}
      onInit={(instance) => {
        const seed = nodes.find((node) => seeds.includes(node.id)) || nodes[0];
        if (seed)
          requestAnimationFrame(() => {
            void instance.setCenter(seed.position.x + 112, seed.position.y + 38, { zoom: 0.9 });
          });
      }}
      onNodeClick={(_, node) => onNode(node.id)}
      onEdgeClick={(_, edge) => onEdge(edge.id)}
      nodesConnectable={false}
      colorMode="light"
    >
      <Background color="#d7dde2" gap={22} />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(node) => String(node.style?.borderColor || '#667084')}
        pannable
        zoomable
      />
    </ReactFlow>
  );
}
export default function GraphPage() {
  return (
    <>
      <PageHeading title="代码关系图" />
      <RequireWorkspace>
        <GraphWorkspace />
      </RequireWorkspace>
    </>
  );
}
function GraphWorkspace() {
  const state = useWorkspace();
  const [kind, setKind] = useState<'symbol' | 'path' | 'commit'>('symbol');
  const [seed, setSeed] = useState('');
  const [hops, setHops] = useState(2);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [edge, setEdge] = useState<GraphEdge | null>(null);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [focus, setFocus] = useState(false);
  const [version, setVersion] = useState<'head' | 'base'>('head');
  const [locator, setLocator] = useState<Locator | null>(null);
  const task = useTask('graph');
  const result = task.task?.result as GraphResult | undefined;
  const graph = version === 'base' ? result?.base_graph : result;
  const kinds = [...new Set(graph?.nodes.map((n) => n.kind) || [])];
  const pathIds = useMemo(() => {
    if (!graph || !selected || !focus) return null;
    const previous = new Map<string, string | null>();
    const queue = [...graph.seed_node_ids];
    queue.forEach((id) => previous.set(id, null));
    while (queue.length) {
      const id = queue.shift()!;
      if (id === selected.id) break;
      for (const relation of graph.edges) {
        const other =
          relation.source_id === id
            ? relation.target_id
            : relation.target_id === id
              ? relation.source_id
              : null;
        if (other && !previous.has(other)) {
          previous.set(other, id);
          queue.push(other);
        }
      }
    }
    const ids = new Set<string>();
    let id: string | null = selected.id;
    while (id && previous.has(id)) {
      ids.add(id);
      id = previous.get(id) || null;
    }
    return ids;
  }, [graph, selected, focus]);
  const visual = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    const list = graph.nodes.filter((n) => !excluded.includes(n.kind));
    const ids = new Set(list.map((n) => n.id));
    const layout = new dagre.graphlib.Graph()
      .setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 100 })
      .setDefaultEdgeLabel(() => ({}));
    list.forEach((n) => layout.setNode(n.id, { width: 224, height: 76 }));
    const relations = graph.edges.filter((e) => ids.has(e.source_id) && ids.has(e.target_id));
    relations.forEach((e) => layout.setEdge(e.source_id, e.target_id));
    dagre.layout(layout);
    const nodes: Node[] = list.map((n) => ({
      id: n.id,
      position: { x: layout.node(n.id).x - 112, y: layout.node(n.id).y - 38 },
      data: {
        label: (
          <div className="graph-node">
            <span style={{ color: colors[n.kind] }}>
              {nodeNames[n.kind] || n.kind} · {n.distance} 跳
            </span>
            <strong>{n.name}</strong>
            <small>{n.path || short(n.commit_sha)}</small>
          </div>
        ),
      },
      style: {
        width: 224,
        height: 76,
        borderColor: colors[n.kind],
        borderWidth: selected?.id === n.id ? 3 : 1,
        opacity: pathIds && !pathIds.has(n.id) ? 0.25 : 1,
      },
      draggable: true,
    }));
    const edges: Edge[] = relations.map((e) => ({
      id: e.id,
      source: e.source_id,
      target: e.target_id,
      label: e.kind,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: {
        stroke: e.inference ? '#ad6f24' : '#8a929d',
        strokeDasharray: e.inference ? '5 4' : undefined,
        opacity: pathIds && (!pathIds.has(e.source_id) || !pathIds.has(e.target_id)) ? 0.12 : 1,
      },
      labelStyle: { fontSize: 10 },
    }));
    return { nodes, edges };
  }, [graph, excluded, selected, pathIds]);
  return (
    <>
      <form
        className="graph-form"
        onSubmit={(e) => {
          e.preventDefault();
          setSelected(null);
          setEdge(null);
          setVersion('head');
          task.start({
            action: 'graph',
            workspace_id: state.workspaceId,
            ref: state.ref,
            seed_kind: kind,
            seed,
            hops,
          });
        }}
      >
        <Field label="起点类型">
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="symbol">函数 / 类</option>
            <option value="path">文件</option>
            <option value="commit">当前提交</option>
          </select>
        </Field>
        {kind !== 'commit' && (
          <Field label={kind === 'symbol' ? '符号名称' : '文件路径'}>
            <input
              aria-label="图起点"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder={kind === 'symbol' ? 'TaskService.create_task' : 'src/service.py'}
              required
            />
          </Field>
        )}
        <Field label="展开层级">
          <select value={hops} onChange={(e) => setHops(Number(e.target.value))}>
            <option value={1}>1 跳</option>
            <option value={2}>2 跳</option>
          </select>
        </Field>
        <button className="button" disabled={task.pending}>
          <Play size={15} />
          构建子图
        </button>
      </form>
      <ErrorBox error={task.error} />
      <TaskProgress task={task.task} />
      {!graph ? (
        <Empty>选择函数、文件或提交查看关系。</Empty>
      ) : (
        <>
          <div className="graph-toolbar">
            <div className="actions">
              <Badge>{visual.nodes.length} 节点</Badge>
              <Badge>{visual.edges.length} 关系</Badge>
              <code className="small">{short(graph.commit_sha)}</code>
              {graph.truncated && <Badge tone="amber">已达到子图上限</Badge>}
              {graph.ambiguous_seed && <Badge tone="amber">同名起点</Badge>}
            </div>
            {result?.base_graph && (
              <select
                aria-label="图版本"
                value={version}
                onChange={(e) => {
                  setVersion(e.target.value as typeof version);
                  setSelected(null);
                  setEdge(null);
                }}
              >
                <option value="head">Head 版本</option>
                <option value="base">Base · 已删除文件</option>
              </select>
            )}
            <label className="check">
              <input type="checkbox" checked={focus} onChange={(e) => setFocus(e.target.checked)} />
              聚焦选中路径
            </label>
          </div>
          <div className="graph-filters">
            {kinds.map((value) => (
              <label className="check" key={value}>
                <input
                  type="checkbox"
                  checked={!excluded.includes(value)}
                  onChange={() =>
                    setExcluded((previous) =>
                      previous.includes(value)
                        ? previous.filter((k) => k !== value)
                        : [...previous, value],
                    )
                  }
                />
                <i style={{ background: colors[value] }} />
                {nodeNames[value] || value}
              </label>
            ))}
          </div>
          <div className="graph-layout">
            <div className="graph-canvas" data-testid="relation-graph">
              <ReactFlowProvider>
                <GraphCanvas
                  key={`${graph.snapshot_id}-${task.task?.id}-${version}`}
                  nodes={visual.nodes}
                  edges={visual.edges}
                  seeds={graph.seed_node_ids}
                  onNode={(id) => {
                    setSelected(graph.nodes.find((n) => n.id === id) || null);
                    setEdge(null);
                  }}
                  onEdge={(id) => {
                    setEdge(graph.edges.find((e) => e.id === id) || null);
                    setSelected(null);
                  }}
                />
              </ReactFlowProvider>
            </div>
            <aside className="graph-detail">
              {selected ? (
                <>
                  <Badge>{nodeNames[selected.kind] || selected.kind}</Badge>
                  <h2>{selected.name}</h2>
                  <p className="mono small">{selected.path}</p>
                  <div className="meta-stack">
                    <span>
                      commit {short(selected.commit_sha || selected.provenance.commit_sha)}
                    </span>
                    <span>层级 {selected.distance}</span>
                  </div>
                  {selected.path && (
                    <EvidenceLink
                      item={{ ...selected, commit_sha: graph.commit_sha }}
                      onOpen={setLocator}
                    />
                  )}
                  {(selected.kind === 'function' || selected.kind === 'class') && (
                    <button
                      className="button secondary"
                      disabled={task.pending}
                      onClick={() => {
                        setSeed(selected.symbol || selected.name);
                        setKind('symbol');
                        setSelected(null);
                        task.start({
                          action: 'graph',
                          workspace_id: state.workspaceId,
                          ref: graph.commit_sha,
                          seed_kind: 'symbol',
                          seed: selected.symbol || selected.name,
                          hops,
                        });
                      }}
                    >
                      <Expand size={15} />
                      从此节点展开
                    </button>
                  )}
                  <details>
                    <summary>来源</summary>
                    <pre>{JSON.stringify(selected.provenance, null, 2)}</pre>
                  </details>
                </>
              ) : edge ? (
                <>
                  <h2>{edge.kind}</h2>
                  <Badge tone={edge.inference ? 'amber' : 'green'}>
                    {edge.inference ? '推测' : '已确认 · 静态关系'}
                  </Badge>
                  <p>{graph.nodes.find((n) => n.id === edge.source_id)?.name}</p>
                  <Network size={18} />
                  <p>{graph.nodes.find((n) => n.id === edge.target_id)?.name}</p>
                  {edge.provenance.path && (
                    <EvidenceLink
                      item={{ ...edge.provenance, evidence_id: edge.evidence_id }}
                      onOpen={setLocator}
                    />
                  )}
                  <details>
                    <summary>来源</summary>
                    <pre>{JSON.stringify(edge.provenance, null, 2)}</pre>
                  </details>
                </>
              ) : (
                <Empty>选择节点或关系查看来源。</Empty>
              )}
            </aside>
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
