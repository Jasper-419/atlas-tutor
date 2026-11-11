"use client";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  AlertCircle,
  Loader2,
  X,
  BookOpen,
  Check,
  ChevronRight,
  Download,
  Pencil,
  RefreshCw,
  Upload,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, Course } from "@/lib/types";
import { api, useResource } from "@/lib/api";
import type { AgentTask } from "@/lib/types";
import "./learning-panels.css";

export function AtlasMark({ size = 30 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M7 32 19 7h2l12 25M13 22h14"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="7" cy="32" r="2.6" fill="currentColor" />
      <circle cx="20" cy="7" r="2.6" fill="currentColor" />
      <circle cx="33" cy="32" r="2.6" fill="currentColor" />
    </svg>
  );
}
export function Loading({
  label = "正在整理你的学习空间…",
}: {
  label?: string;
}) {
  return (
    <div className="loading-state" role="status">
      <Loader2 size={20} className="spin" />
      <span>{label}</span>
    </div>
  );
}
export function ErrorBox({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <div>{message}</div>
      {retry && (
        <button className="text-button" onClick={retry}>
          重试
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <BookOpen size={27} strokeWidth={1.2} />
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {children}
    </div>
  );
}
export function PageTitle({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-title">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="title-actions">{children}</div>}
    </header>
  );
}
export function Progress({ value = 0 }: { value?: number }) {
  return (
    <div
      className="progress-track"
      role="progressbar"
      aria-label="学习进度"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
    >
      <span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}
export const statusLabels: Record<string, string> = {
  draft: "待规划",
  planning: "规划中",
  active: "学习中",
  failed: "规划失败",
  completed: "已完成",
  queued: "等待执行",
  running: "执行中",
  succeeded: "已完成",
  cancelled: "已取消",
  mastered: "已掌握",
  learning: "正在学习",
  available: "可开始",
  locked: "待解锁",
};
export function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value}`}>
      <i />
      {statusLabels[value] || value}
    </span>
  );
}
export function Breadcrumb({
  items,
}: {
  items: { label: string; href?: string }[];
}) {
  return (
    <div className="breadcrumbs">
      {items.map((item, i) => (
        <span key={i}>
          {i > 0 && <ChevronRight size={12} />}
          {item.href ? <Link href={item.href}>{item.label}</Link> : item.label}
        </span>
      ))}
    </div>
  );
}
export function CourseRow({ course }: { course: Course }) {
  return (
    <Link href={`/courses/${course.id}`} className="course-row">
      <div className="course-number">
        <BookOpen size={19} strokeWidth={1.4} />
      </div>
      <div className="course-row-main">
        <strong>{course.title}</strong>
        <span>
          {course.total_nodes} 个知识节点 · 每日 {course.minutes_per_day} 分钟
        </span>
      </div>
      <div className="course-row-progress">
        <span>{Math.round(course.progress)}%</span>
        <Progress value={course.progress} />
      </div>
      <Status value={course.status} />
      <ArrowRight size={17} />
    </Link>
  );
}
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
export function Citations({ items }: { items: Citation[] }) {
  const [selected, setSelected] = useState<Citation | null>(null);
  if (!items?.length) return null;
  return (
    <>
    <div className="citations">
      <span className="muted small">参考资料</span>
      {items.map((c, i) => (
        <button type="button" className="citation-trigger" key={`${c.id || c.source_id}-${i}`} onClick={() => setSelected(c)}>
            <span className="citation-index">{i + 1}</span>
            <span>{c.title}<small>v{(c as LocatedCitation).source_version || 1}{(c as LocatedCitation).page_start ? ` · 第 ${(c as LocatedCitation).page_start} 页` : ""}</small></span><span className="citation-read-label">阅读原文</span>
        </button>
      ))}
    </div>
    {selected && <SourceDialog sourceId={selected.source_id} version={(selected as LocatedCitation).source_version || 1} citation={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

type LocatedCitation = Citation & { source_version?: number; page_start?: number | null; page_end?: number | null; section?: string | null };
type SourceDocument = { id: string; title: string; content: string; version: number; current_version: number; kind: string; url?: string | null; filename?: string | null; pages?: { page: number; text: string }[]; index?: { state: string; can_rebuild: boolean } };

const indexLabels: Record<string, string> = {
  ready: "向量索引就绪",
  lexical: "关键词检索",
  embedding_unverified: "旧向量待重建 · 关键词检索",
  embedding_model_changed: "模型已切换 · 关键词检索",
  embedding_unavailable: "向量服务未配置 · 关键词检索",
};

export function SourceDialog({ sourceId, version = 1, citation, editable = false, onClose, onChanged }: {
  sourceId: string; version?: number; citation?: LocatedCitation; editable?: boolean; onClose: () => void; onChanged?: () => void;
}) {
  const { data: source, error, loading, reload, setData } = useResource<SourceDocument>(`/sources/${encodeURIComponent(sourceId)}?version=${version}`);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [task, setTask] = useState<AgentTask | null>(null);
  const [notice, setNotice] = useState("");
  const focus = useRef<HTMLElement>(null);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { if (source) { setTitle(source.title); setContent(source.content || ""); } }, [source]);
  useEffect(() => {
    if (source && !editing) focus.current?.scrollIntoView({ block: "center" });
  }, [source, editing]);
  useEffect(() => {
    if (!task || ["succeeded", "failed", "cancelled"].includes(task.status)) return;
    let active = true;
    const timer = setInterval(() => {
      void api<AgentTask>(`/tasks/${task.id}`).then((updated) => {
        if (!active) return;
        setTask(updated);
      }).catch((e) => { if (active) setSaveError((e as Error).message); });
    }, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [task?.id, task?.status, onChanged, sourceId, setData]);
  useEffect(() => {
    if (!task || !["succeeded", "failed", "cancelled"].includes(task.status)) return;
    if (task.status !== "succeeded") {
      setSaveError(task.error || (task.kind === "reindex" ? "重建未完成，可以在任务页重试。" : "替换未完成，可以重新选择文件。"));
      return;
    }
    let active = true;
    setNotice(task.kind === "reindex" ? "资料索引已重建。" : "新版本已保存，相关讲义可重新生成。");
    onChanged?.();
    void api<SourceDocument>(`/sources/${encodeURIComponent(sourceId)}`).then((latest) => { if (active) setData(latest); }).catch((e) => { if (active) setSaveError((e as Error).message); });
    return () => { active = false; };
  }, [task?.id, task?.status, sourceId, onChanged, setData]);
  const current = !!source && source.version === source.current_version;
  const replacing = !!task && !["succeeded", "failed", "cancelled"].includes(task.status);
  const excerpt = citation?.excerpt?.trim();
  function locatedText(text: string) {
    if (!excerpt) return text;
    const needle = excerpt.replace(/^[.…\s]+|[.…\s]+$/g, "");
    const index = needle.length > 5 ? text.indexOf(needle) : -1;
    if (index < 0) return text;
    return <>{text.slice(0, index)}<mark ref={focus}>{text.slice(index, index + needle.length)}</mark>{text.slice(index + needle.length)}</>;
  }
  return <Modal title={source?.title || "资料原文"} className="source-document-modal" onClose={onClose}>
    {loading ? <Loading label="正在读取原文…" /> : error || !source ? <ErrorBox message={error || "资料暂时不可用"} retry={reload} /> : <>
      <div className="source-document-toolbar"><span>{source.kind.toUpperCase()} · v{source.version}{!current && ` · 当前为 v${source.current_version}`}{citation?.section && ` · ${citation.section}`}</span><div>
        {source.url && <a className="text-button" href={source.url} target="_blank" rel="noopener noreferrer">原始来源 ↗</a>}
        <a className="button" href={`/api/sources/${encodeURIComponent(sourceId)}/download?version=${source.version}`} download><Download size={14} />下载</a>
        {editable && current && !editing && <button className="button" disabled={busy || replacing} onClick={() => { setEditing(true); setSaveError(""); }}><Pencil size={14} />编辑文本</button>}
        {editable && current && <button className="button" disabled={busy || replacing || editing} onClick={() => file.current?.click()}><Upload size={14} />替换原文件</button>}
        <input type="file" hidden ref={file} accept=".pdf,.txt,.md,.docx" onChange={async (event) => {
          const replacement = event.target.files?.[0]; if (!replacement) return;
          const body = new FormData(); body.set("file", replacement); body.set("expected_version", String(source.current_version));
          setBusy(true); setSaveError(""); setNotice("");
          try { setTask(await api<AgentTask>(`/sources/${encodeURIComponent(sourceId)}/replace`, { method: "POST", body })); }
          catch (e) { setSaveError((e as Error).message); } finally { setBusy(false); event.target.value = ""; }
        }} />
      </div></div>
      {editable && current && !editing && source.index && (
        <div className="source-document-toolbar">
          <span>{indexLabels[source.index.state] || "关键词检索"}</span>
          {source.index.can_rebuild && (
            <button className="button" disabled={busy || replacing} onClick={async () => {
              setBusy(true); setSaveError(""); setNotice("");
              try {
                setTask(await api<AgentTask>(`/sources/${encodeURIComponent(sourceId)}/reindex`, {
                  method: "POST", body: JSON.stringify({ expected_version: source.current_version }),
                }));
              } catch (e) {
                setSaveError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}><RefreshCw size={14} />重建索引</button>
          )}
        </div>
      )}
      {saveError && <ErrorBox message={saveError} />}
      {notice && <p className="learning-status" role="status">{notice}</p>}
      {task && <p className="muted small" role="status">{task.message || "正在更新资料索引…"} <Link href={`/tasks?task=${task.id}`}>查看任务</Link></p>}
      {editing ? <form className="form-stack source-document-editor" onSubmit={async (event) => {
        event.preventDefault(); setBusy(true); setSaveError("");
        try {
          const updated = await api<SourceDocument>(`/sources/${encodeURIComponent(sourceId)}`, { method: "PUT", body: JSON.stringify({ title, content, expected_version: source.current_version }) });
          setData({ ...source, ...updated, title, content, pages: updated.pages || [], current_version: updated.current_version || updated.version }); setEditing(false); setNotice("新版本已保存，相关讲义可重新生成。"); onChanged?.();
        } catch (e) { setSaveError((e as Error).message); } finally { setBusy(false); }
      }}><label>资料标题<input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} /></label><label>资料正文<textarea rows={16} value={content} onChange={(e) => setContent(e.target.value)} required minLength={20} maxLength={200000} /></label><div className="learning-actions"><button type="button" className="button" disabled={busy} onClick={() => { setEditing(false); setTitle(source.title); setContent(source.content); }}>取消</button><button className="button primary" disabled={busy || !content.trim()}>{busy ? "正在保存…" : "保存新版本"}</button></div></form> : <div className="source-document-body">
        {citation && <div className="source-citation-location" ref={!source.pages?.length ? focus as React.RefObject<HTMLDivElement> : undefined}><strong>引用位置{citation.page_start ? ` · 第 ${citation.page_start}${citation.page_end && citation.page_end !== citation.page_start ? `–${citation.page_end}` : ""} 页` : typeof citation.chunk_index === "number" ? ` · 片段 ${citation.chunk_index + 1}` : ""}</strong>{citation.excerpt && <p>{citation.excerpt}</p>}</div>}
        {source.pages?.length ? source.pages.map((page) => <section key={page.page} ref={citation?.page_start === page.page ? focus as React.RefObject<HTMLElement> : undefined} className={citation?.page_start === page.page ? "source-page cited-page" : "source-page"}><h3>第 {page.page} 页</h3><div className="source-plain-text">{locatedText(page.text)}</div></section>) : citation ? <div className="source-plain-text">{locatedText(source.content)}</div> : <Markdown>{source.content}</Markdown>}
      </div>}
    </>}
  </Modal>;
}
export function Modal({
  title,
  onClose,
  children,
  className = "",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    d?.showModal();
    return () => {
      d?.close();
    };
  }, []);
  const dismiss = () => {
    ref.current?.close();
    onClose();
  };
  return (
    <dialog
      ref={ref}
      className={`modal ${className}`}
      aria-label={title}
      onCancel={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        event.stopPropagation();
        dismiss();
      }}
      onKeyDown={(event) => {
        const dialog = ref.current;
        if (
          event.key !== "Tab" ||
          !dialog ||
          (event.target as Element).closest("dialog") !== dialog
        )
          return;
        const items = Array.from(
          dialog.querySelectorAll<HTMLElement>(
            "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]",
          ),
        ).filter(
          (element) =>
            element.tabIndex >= 0 &&
            element.getClientRects().length > 0 &&
            element.closest("dialog") === dialog,
        );
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onClick={(e) => {
        if (e.target === ref.current) dismiss();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="关闭" onClick={dismiss}>
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Check size={17} />
      {children}
    </div>
  );
}
