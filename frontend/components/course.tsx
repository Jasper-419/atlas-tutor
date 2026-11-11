"use client";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  Position,
  MarkerType,
  type Node as FlowNode,
} from "@xyflow/react";
import {
  ArrowRight,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Network,
  Files,
  Clock,
  ChevronRight,
  LockKeyhole,
  Check,
  Upload,
  FileText,
  Plus,
  Trash2,
  RefreshCw,
  Loader2,
  Search,
  Globe,
  Pencil,
} from "lucide-react";
import { api, post, useResource, formatDate } from "@/lib/api";
import type {
  CourseDetail,
  KnowledgeNode,
  AgentTask,
  Citation,
  Source,
} from "@/lib/types";
import { useAtlas } from "./atlas-app";
import {
  PageTitle,
  Loading,
  ErrorBox,
  Status,
  Progress,
  Empty,
  Modal,
  Citations,
  SourceDialog,
} from "./ui";
import { NotesButton, TeachingPanel } from "./learning-panels";
import { KnowledgeEngine } from "./knowledge-engine";

export function CourseScreen({ id }: { id: string }) {
  const router = useRouter(),
    { notify } = useAtlas(),
    {
      data: c,
      error,
      loading,
      reload,
    } = useResource<CourseDetail>(`/courses/${id}`, 5000);
  const [tab, setTab] = useState("overview"),
    [modal, setModal] = useState(""),
    [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState("");
  if (loading) return <Loading label="正在展开你的知识地图…" />;
  if (error || !c)
    return <ErrorBox message={error || "课程不存在"} retry={reload} />;
  function replan(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const prompt = `请调整这门课程的学习路径。我的要求：${String(f.get("reason") || "结合我的学习进度调整")}。请先展示精确的变更预览，等我确认后再保存。`;
    router.push(`/chat?course=${encodeURIComponent(id)}&prompt=${encodeURIComponent(prompt)}`);
  }
  return (
    <div className="course-detail">
      <div className="course-heading">
        <Link href="/courses" className="course-back">
          <ArrowLeft size={15} />
          我的课程
        </Link>
        <PageTitle title={c.title}>
          <NotesButton courseId={id} />
          <button
            className="button"
            onClick={() => setModal("replan")}
            disabled={c.status === "planning"}
          >
            <RefreshCw size={15} />
            调整路径
          </button>
          {c.next_node_id && (
            <Link
              className="button primary"
              href={`/courses/${id}/learn/${c.next_node_id}`}
            >
              继续学习 <ArrowRight size={16} />
            </Link>
          )}
        </PageTitle>
        <div className="course-summary">
          <div className="course-meta">
            <Status value={c.status} />
            <span>
              <BookOpen size={14} />
              {c.total_nodes} 个知识节点
            </span>
            <span>
              <Clock size={14} />
              每日 {c.minutes_per_day} 分钟
            </span>
          </div>
          <div className="course-progress">
            <div>
              <span>
                已掌握 {c.mastered_nodes} / {c.total_nodes} 个节点
              </span>
              <strong>{Math.round(c.progress)}%</strong>
            </div>
            <Progress value={c.progress} />
          </div>
        </div>
        {(c.status === "planning" || c.status === "failed") && c.task_id && (
          <PlanningProgress id={c.task_id} onChanged={reload} />
        )}
      </div>
      <div className="tabs course-tabs">
        {[
          ["overview", "学习路径", BookOpen],
          ["graph", "知识图谱", Network],
          ["sources", "课程资料", Files],
        ].map(([v, l, Icon]) => (
          <button
            key={String(v)}
            onClick={() => setTab(String(v))}
            className={tab === v ? "active" : ""}
          >
            {typeof Icon !== "string" && <Icon size={16} />}
            {String(l)}
            {v === "sources" && (
              <span className="count">{c.sources.length}</span>
            )}
          </button>
        ))}
      </div>
      <div className="course-tab-content">
        {tab === "overview" && (
          <div className="course-overview-grid">
            <section className="panel node-list">
              {c.nodes.length ? (
                c.nodes.map((n, i) => (
                  <NodeRow
                    node={n}
                    courseId={id}
                    index={i}
                    key={n.id}
                    onEdit={() => {
                      setModal(n.id);
                      setActionError("");
                    }}
                  />
                ))
              ) : (
                <Empty
                  title="知识路径正在生长"
                  description="课程规划完成后，会在这里展开。"
                />
              )}
            </section>
            <aside className="course-details">
              <TeachingPanel courseId={id} revision={c.updated_at} onChanged={reload} />
              <section className="course-facts">
                <h2>学习目标</h2>
                <p className="muted course-context">{c.goal}</p>
                {c.background && (
                  <details className="course-background">
                    <summary>已有基础</summary>
                    <p>{c.background}</p>
                  </details>
                )}
                <div className="key-value">
                  <span>每日投入</span>
                  <strong>{c.minutes_per_day} 分钟</strong>
                </div>
                <div className="key-value">
                  <span>预计学习</span>
                  <strong>
                    {c.nodes.reduce((s, n) => s + n.estimated_minutes, 0)} 分钟
                  </strong>
                </div>
                <div className="key-value">
                  <span>创建时间</span>
                  <span>{formatDate(c.created_at, true)}</span>
                </div>
                {c.deadline && (
                  <div className="key-value">
                    <span>目标日期</span>
                    <span>{c.deadline}</span>
                  </div>
                )}
              </section>
              <details className="course-history">
                <summary>
                  路径版本<span>v{c.plan_version}</span>
                  <ChevronRight size={15} aria-hidden="true" />
                </summary>
                {c.plan_versions?.map((v, i) => (
                  <div className="version-row" key={`${v.version}-${i}`}>
                    <span>v{v.version}</span>
                    <div>
                      <p>{v.reason}</p>
                      <small className="muted">
                        {formatDate(v.created_at)}
                      </small>
                    </div>
                  </div>
                ))}
              </details>
              <button
                className="text-button danger delete-course"
                onClick={() => setModal("delete")}
              >
                <Trash2 size={14} />
                删除这门课程
              </button>
            </aside>
          </div>
        )}
        {tab === "graph" && <KnowledgeGraph course={c} onChanged={reload} />}
        {tab === "sources" && <SourcesPanel course={c} reload={reload} />}
      </div>
      {modal === "replan" && (
        <Modal title="让路径适应现在的你" onClose={() => setModal("")}>
          <form onSubmit={replan} className="form-stack">
            <p className="muted">
              告诉 Atlas 需要调整什么。前往学习对话查看逐项变更，确认后才会更新路径。
            </p>
            <label>
              调整原因
              <textarea
                name="reason"
                rows={4}
                required
                minLength={4}
                maxLength={2000}
                placeholder="例如：基础部分我已经掌握，想增加实际项目；或最近时间变少，希望缩短每天的学习。"
              />
            </label>
            {actionError && <ErrorBox message={actionError} />}
            <button className="button primary" disabled={busy}>
              {busy ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <RefreshCw size={15} />
              )}
              前往对话预览变更
            </button>
          </form>
        </Modal>
      )}
      {modal === "delete" && (
        <Modal title="删除这门课程？" onClose={() => setModal("")}>
          <p className="muted">
            课程、资料、对话和相关学习记录将被删除。此操作无法撤销。
          </p>
          {actionError && <ErrorBox message={actionError} />}
          <div className="modal-actions">
            <button className="button" onClick={() => setModal("")}>
              保留课程
            </button>
            <button
              className="button danger-button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api(`/courses/${id}`, { method: "DELETE" });
                  router.push("/courses");
                  notify("课程已删除。");
                } catch (e) {
                  setActionError((e as Error).message);
                  setBusy(false);
                }
              }}
            >
              删除课程
            </button>
          </div>
        </Modal>
      )}
      {modal && !["replan", "delete"].includes(modal) && (
        <EditNode
          node={c.nodes.find((n) => n.id === modal)!}
          onClose={() => setModal("")}
          onSaved={() => {
            setModal("");
            reload();
          }}
        />
      )}
    </div>
  );
}
function NodeRow({
  node: n,
  courseId,
  index,
  onEdit,
}: {
  node: KnowledgeNode;
  courseId: string;
  index: number;
  onEdit: () => void;
}) {
  return (
    <div className={`node-row node-${n.status}`}>
      <div className="node-state">
        {n.status === "mastered" ? (
          <Check size={16} />
        ) : n.status === "locked" ? (
          <LockKeyhole size={14} />
        ) : (
          String(index + 1).padStart(2, "0")
        )}
      </div>
      <div className="node-info">
        <h3>{n.title}</h3>
        <p>{n.summary}</p>
        <div className="node-sub">
          <span>{n.estimated_minutes} 分钟</span>
          <span>掌握度 {Math.round(n.mastery)}%</span>
          <Status value={n.status} />
        </div>
      </div>
      <div className="node-actions">
        <button
          className="icon-button"
          aria-label={`编辑 ${n.title}`}
          onClick={onEdit}
        >
          <Pencil size={14} />
        </button>
        {n.status !== "locked" ? (
          <Link
            className="icon-button"
            href={`/courses/${courseId}/learn/${n.id}`}
            aria-label={`学习 ${n.title}`}
          >
            <ChevronRight size={19} />
          </Link>
        ) : (
          <LockKeyhole size={14} />
        )}
      </div>
    </div>
  );
}
function EditNode({
  node,
  onClose,
  onSaved,
}: {
  node: KnowledgeNode;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Modal title="编辑知识节点" onClose={onClose}>
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          try {
            await api(`/nodes/${node.id}`, {
              method: "PATCH",
              body: JSON.stringify({
                ...Object.fromEntries(f),
                estimated_minutes: Number(f.get("estimated_minutes")),
              }),
            });
            onSaved();
          } catch (e) {
            setError((e as Error).message);
            setBusy(false);
          }
        }}
      >
        <label>
          节点标题
          <input
            name="title"
            defaultValue={node.title}
            required
            maxLength={200}
          />
        </label>
        <label>
          学习目标
          <textarea
            name="objective"
            defaultValue={node.objective}
            rows={2}
            required
          />
        </label>
        <label>
          简介
          <textarea
            name="summary"
            defaultValue={node.summary}
            rows={3}
            required
          />
        </label>
        <label>
          预计分钟
          <input
            type="number"
            name="estimated_minutes"
            min={5}
            max={240}
            defaultValue={node.estimated_minutes}
          />
        </label>
        {error && <ErrorBox message={error} />}
        <button className="button primary" disabled={busy}>
          保存节点
        </button>
      </form>
    </Modal>
  );
}
export function PlanningProgress({
  id,
  onChanged,
}: {
  id: string;
  onChanged?: () => void;
}) {
  const {
      data: t,
      error,
      reload,
    } = useResource<AgentTask>(`/tasks/${id}`, 2500),
    [busy, setBusy] = useState(false);
  if (error) return <ErrorBox message={error} retry={reload} />;
  if (!t) return <Loading label="正在读取规划进度…" />;
  return (
    <div
      className={`planning-progress ${t.status === "failed" ? "planning-failed" : ""}`}
    >
      <div className="planning-top">
        {["queued", "running"].includes(t.status) && (
          <Loader2 className="spin" size={19} />
        )}
        <div>
          <strong>{t.message || "Atlas 正在连接知识节点"}</strong>
          <p>{t.error || "目标与约束已保存，可随时离开，回来后继续查看。"}</p>
        </div>
        <Status value={t.status} />
      </div>
      <Progress value={t.progress} />
      <div className="planning-footer">
        <Link href={`/tasks?task=${t.id}`} className="text-link">
          查看执行步骤 <ArrowUpRight size={13} />
        </Link>
        {["failed", "cancelled"].includes(t.status) && (
          <button
            className="text-button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await post(`/tasks/${id}/retry`);
                reload();
                onChanged?.();
              } finally {
                setBusy(false);
              }
            }}
          >
            重试任务 <RefreshCw size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

function KnowledgeGraph({
  course: c,
  onChanged,
}: {
  course: CourseDetail;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false),
    [edges, setEdges] = useState(c.edges),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const nodes = useMemo(() => {
    const depth: Record<string, number> = {};
    const getDepth = (id: string, visited = new Set<string>()): number => {
      if (depth[id] !== undefined) return depth[id];
      if (visited.has(id)) return 0;
      visited.add(id);
      const parent = c.edges
        .filter((e) => e.target === id)
        .map((e) => e.source);
      return (depth[id] = parent.length
        ? Math.max(...parent.map((p) => getDepth(p, new Set(visited)))) + 1
        : 0);
    };
    const rows: Record<number, number> = {};
    return c.nodes.map((n) => {
      const d = getDepth(n.id),
        r = rows[d] || 0;
      rows[d] = r + 1;
      return {
        id: n.id,
        position: { x: d * 275, y: r * 155 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        type: "default",
        className: `graph-node graph-node-${n.status}`,
        data: {
          label: (
            <div>
              <span className="small muted">
                {String(n.position + 1).padStart(2, "0")} ·{" "}
                {n.estimated_minutes} 分钟
              </span>
              <strong>{n.title}</strong>
              <span className="graph-node-bottom">
                <Status value={n.status} />
                <span>{Math.round(n.mastery)}%</span>
              </span>
            </div>
          ),
        },
      } as FlowNode;
    });
  }, [c.nodes, c.edges]);
  return (
    <>
      <div className="graph-toolbar">
        <div className="graph-legend">
          <span>
            <i className="mastered" />
            已掌握
          </span>
          <span>
            <i className="available" />
            可学习
          </span>
          <span>
            <i />
            待解锁
          </span>
        </div>
        <button
          className="button small-button"
          onClick={() => {
            setEditing(!editing);
            setEdges(c.edges);
          }}
        >
          编辑先修关系
        </button>
      </div>
      <div className="knowledge-graph">
        <ReactFlow
          nodes={nodes}
          edges={c.edges.map((e, i) => ({
            id: `e${i}`,
            source: e.source,
            target: e.target,
            type: "smoothstep",
            style: { stroke: "#b8c6be", strokeWidth: 1.5 },
            markerEnd: { type: MarkerType.ArrowClosed, color: "#b8c6be" },
          }))}
          fitView
          fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
          minZoom={0.15}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, n) => {
            const node = c.nodes.find((x) => x.id === n.id);
            if (node && node.status !== "locked")
              window.location.assign(`/courses/${c.id}/learn/${n.id}`);
          }}
        >
          <Background color="#d9ded7" gap={22} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <p className="small muted graph-caption">
        连线表示先修关系。掌握前置知识后，后续节点会解锁；点击可学习节点进入课程。
      </p>
      {editing && (
        <Modal title="编辑先修关系" onClose={() => setEditing(false)}>
          <p className="muted">
            选择每个节点需要先掌握的知识。系统会拒绝循环依赖。
          </p>
          <div className="edge-editor">
            {c.nodes.map((n) => (
              <div key={n.id}>
                <strong>{n.title}</strong>
                <div>
                  {c.nodes
                    .filter((p) => p.id !== n.id)
                    .map((p) => (
                      <label key={p.id}>
                        <input
                          type="checkbox"
                          checked={edges.some(
                            (e) => e.source === p.id && e.target === n.id,
                          )}
                          onChange={(e) =>
                            setEdges(
                              e.target.checked
                                ? [...edges, { source: p.id, target: n.id }]
                                : edges.filter(
                                    (x) =>
                                      !(x.source === p.id && x.target === n.id),
                                  ),
                            )
                          }
                        />
                        {p.title}
                      </label>
                    ))}
                </div>
              </div>
            ))}
          </div>
          {error && <ErrorBox message={error} />}
          <div className="modal-actions">
            <button
              className="button primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api(`/courses/${c.id}/graph`, {
                    method: "PUT",
                    body: JSON.stringify({ edges }),
                  });
                  setEditing(false);
                  onChanged();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              保存先修关系
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function SourcesPanel({
  course: c,
  reload,
}: {
  course: CourseDetail;
  reload: () => void;
}) {
  const { notify } = useAtlas(),
    [modal, setModal] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<Citation[] | null>(null),
    [research, setResearch] = useState(""),
    [selectedSource, setSelectedSource] = useState<Source | null>(null),
    [importId, setImportId] = useState<string | null>(null);
  const { data: importTask, error: importError } = useResource<AgentTask>(
    importId ? `/tasks/${importId}` : null, 1800,
  );
  useEffect(() => {
    if (importId && importTask?.id === importId && ["succeeded", "failed", "cancelled"].includes(importTask.status)) {
      setImportId(null);
      if (importTask.status === "succeeded") reload();
    }
  }, [importId, importTask, reload]);
  return (
    <>
      <div className="sources-header">
        <div>
          <h2>课程资料</h2>
          <p className="muted">
            资料仅用于本课程，Tutor 会检索相关片段并给出引用。
          </p>
        </div>
        <div className="row-actions">
          <label className="button">
            <Upload size={15} />
            {busy ? "正在提交…" : "上传资料"}
            <input
              type="file"
              accept=".pdf,.txt,.md,.docx"
              hidden
              disabled={busy}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setBusy(true);
                setError("");
                const fd = new FormData();
                fd.append("file", f);
                try {
                  const task = await api<AgentTask>(`/courses/${c.id}/imports`, {
                    method: "POST",
                    body: fd,
                  });
                  setImportId(task.id);
                  notify("资料导入已排队。");
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                  e.target.value = "";
                }
              }}
            />
          </label>
          <button className="button" onClick={() => setModal(true)}>
            <Plus size={15} />
            添加文本
          </button>
        </div>
      </div>
      {error && <ErrorBox message={error} />}
      {importError && <ErrorBox message={importError} />}
      {(importId || importTask) && <p className="small muted" role="status">
        {importTask?.message || "等待导入"}{importTask?.error && ` · ${importTask.error}`}{" "}
        <Link href={`/tasks?task=${importId || importTask?.id}`}>查看任务</Link>
      </p>}
      <KnowledgeEngine key={c.id} courseId={c.id} />
      <div className="sources-grid">
        <section className="panel">
          {c.sources.length ? (
            c.sources.map((s) => (
              <div className="source-row" key={s.id}>
                <FileText size={19} strokeWidth={1.3} />
                <div>
                  <button className="source-title-button" onClick={() => setSelectedSource(s)}>{s.title}</button>
                  <small>
                    {s.kind.toUpperCase()} · v{(s as Source & { version?: number }).version || 1} · {s.chunk_count} 个资料片段 ·{" "}
                    {formatDate(s.created_at, true)}
                  </small>
                  {s.url && (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="small text-link"
                    >
                      原始来源 ↗
                    </a>
                  )}
                  <div className="source-row-tools"><button className="text-button" onClick={() => setSelectedSource(s)}>{s.kind === "research" ? "阅读全文报告" : "查看全文与更新"}</button></div>
                </div>
                <button
                  className="icon-button"
                  aria-label={`删除资料 ${s.title}`}
                  onClick={async () => {
                    try {
                      await api(`/sources/${s.id}`, { method: "DELETE" });
                      reload();
                      notify("资料已删除。");
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))
          ) : (
            <Empty
              title="为课程添一份可靠的资料"
              description="上传 PDF、TXT、Markdown 或 DOCX，或添加你整理的文本。"
            />
          )}
        </section>
        <aside className="panel research-panel">
          <Globe size={23} strokeWidth={1.3} />
          <h2>让 Atlas 找找资料</h2>
          <p className="muted">
            研究任务会查找和筛选资料，记录来源与执行过程。
          </p>
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                const t = await post<AgentTask>(`/courses/${c.id}/research`, {
                  query: research,
                });
                notify("研究任务已创建。");
                window.location.assign(`/tasks?task=${t.id}`);
              } catch (e) {
                setError((e as Error).message);
                setBusy(false);
              }
            }}
          >
            <textarea
              rows={3}
              aria-label="资料研究目标"
              placeholder="需要研究的问题，或一篇官方文档的 URL"
              value={research}
              onChange={(e) => setResearch(e.target.value)}
              required
              minLength={4}
            />
            <button className="button" disabled={busy}>
              开始研究 <ArrowRight size={15} />
            </button>
          </form>
        </aside>
      </div>
      <form
        className="source-search"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            setResults(
              await api<Citation[]>(
                `/courses/${c.id}/search?q=${encodeURIComponent(query)}`,
              ),
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="search-field">
          <Search size={17} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="在本课程资料中检索一个概念…"
            required
          />
        </label>
        <button className="button" disabled={busy}>
          检索资料
        </button>
      </form>
      {results && (
        <div className="panel">
          {results.length ? (
            <Citations items={results} />
          ) : (
            <p className="muted">
              没有找到足够相关的资料片段，试试其他关键词。
            </p>
          )}
        </div>
      )}
      {modal && (
        <Modal title="添加课程资料" onClose={() => setModal(false)}>
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              setBusy(true);
              setError("");
              try {
                await post(`/courses/${c.id}/sources/text`, {
                  title: f.get("title"),
                  content: f.get("content"),
                  url: f.get("url") || null,
                });
                setModal(false);
                reload();
                notify("文本资料已加入知识库。");
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              资料标题
              <input name="title" required maxLength={200} />
            </label>
            <label>
              来源链接 <span className="muted">（可选）</span>
              <input name="url" type="url" placeholder="https://…" />
            </label>
            <label>
              资料内容
              <textarea
                name="content"
                rows={9}
                required
                minLength={20}
                maxLength={200000}
              />
            </label>
            {error && <ErrorBox message={error} />}
            <button className="button primary" disabled={busy}>
              {busy ? "正在整理…" : "加入课程资料"}
            </button>
          </form>
        </Modal>
      )}
      {selectedSource && <SourceDialog sourceId={selectedSource.id} version={(selectedSource as Source & { version?: number }).version || 1} editable onClose={() => setSelectedSource(null)} onChanged={reload} />}
    </>
  );
}
