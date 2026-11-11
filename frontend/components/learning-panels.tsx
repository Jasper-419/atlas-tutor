"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Download, Flag, NotebookPen, Pencil, Plus } from "lucide-react";
import { api, formatDate, post, uid, useResource } from "@/lib/api";
import type { Citation } from "@/lib/types";
import { Citations, Empty, ErrorBox, Loading, Markdown, Modal } from "./ui";
import "./learning-panels.css";

export type LearningNote = { id: string; course_id: string | null; title: string; content: string; version: number; sources: Citation[]; created_at: string; updated_at: string };
type TeachingState = { node_id?: string | null; node_title?: string; phase?: string; mastery?: number; deferred_until?: string | null; next_action?: { kind: string; label: string; reason?: string; node_id?: string | null; prompt?: string }; feedback?: unknown[]; misconceptions?: { id?: string; content?: string; description?: string; status?: string }[] };
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";

export function NotesButton({ courseId }: { courseId?: string }) {
  const [open, setOpen] = useState(false);
  return <><button className="button" onClick={() => setOpen(true)}><NotebookPen size={15} />学习笔记</button>{open && <NotesDrawer courseId={courseId} onClose={() => setOpen(false)} />}</>;
}

export function SaveTurnNote({ turnId, onSaved }: { turnId: string; onSaved: (note: LearningNote) => void }) {
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<LearningNote | null>(null);
  const [error, setError] = useState("");
  return <div className="turn-note-action"><button className="text-button" disabled={busy} onClick={async () => {
    if (saved) { onSaved(saved); return; }
    setBusy(true); setError("");
    try { const note = await post<LearningNote>(`/tutor/turns/${turnId}/note`); setSaved(note); onSaved(note); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }}><NotebookPen size={14} />{busy ? "正在保存…" : saved ? "查看已保存笔记" : "保存笔记"}</button>{error && <ErrorBox message={error} />}</div>;
}

export function NotesDrawer({ courseId, initialNote, onClose }: { courseId?: string; initialNote?: LearningNote | null; onClose: () => void }) {
  const { data: allNotes, error, loading, reload } = useResource<LearningNote[]>(`/notes${courseId ? `?course_id=${encodeURIComponent(courseId)}` : ""}`);
  const notes = allNotes?.filter((note) => courseId ? note.course_id === courseId : !note.course_id);
  const [selected, setSelected] = useState<LearningNote | null>(initialNote && (courseId ? initialNote.course_id === courseId : !initialNote.course_id) ? initialNote : null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef(uid());
  const readVersion = useRef(0);
  useEffect(() => {
    if (selected || !notes?.length) return;
    setSelected(notes[0]);
  }, [allNotes]);
  async function select(note: LearningNote) {
    if (busy) return;
    const version = ++readVersion.current; setBusy(true); setLoadError("");
    try {
      const fresh = await api<LearningNote>(`/notes/${note.id}`);
      if (readVersion.current !== version) return;
      setSelected(fresh); setEditing(false); setCreating(false); setNotice("");
    } catch (e) { if (readVersion.current === version) setLoadError(errorMessage(e)); }
    finally { if (readVersion.current === version) setBusy(false); }
  }
  function edit() {
    if (!selected) return;
    setTitle(selected.title); setContent(selected.content); setEditing(true); setCreating(false); setLoadError(""); setNotice("");
  }
  return <Modal title={courseId ? "课程笔记" : "个人笔记"} className="learning-notes-modal" onClose={onClose}>
    <div className="learning-notes-toolbar"><span className="muted small">{courseId ? "保存在当前课程" : "未关联课程的笔记"}{notes ? ` · ${notes.length} 篇` : ""}</span><button className="button" disabled={busy} onClick={() => { setCreating(true); setEditing(true); setTitle(""); setContent(""); setLoadError(""); setNotice(""); request.current = uid(); }}><Plus size={14} />新笔记</button></div>
    <div className="learning-notes-layout">
      <nav className="learning-notes-list" aria-label="笔记列表">
        {loading ? <Loading label="读取笔记…" /> : error ? <ErrorBox message={error} retry={reload} /> : notes?.length ? notes.map((note) => <button key={note.id} className={selected?.id === note.id && !creating ? "selected" : ""} disabled={busy} onClick={() => void select(note)}><strong>{note.title}</strong><small>v{note.version} · {formatDate(note.updated_at, true)}</small></button>) : <p className="muted small">还没有笔记。可以保存聊天回答，或写下自己的理解。</p>}
      </nav>
      <div className="learning-note-detail" aria-busy={busy}>
        {loadError && <ErrorBox message={loadError} />}
        {notice && <p className="learning-status" role="status">{notice}</p>}
        {editing ? <form className="form-stack" onSubmit={async (event) => {
          event.preventDefault(); if (busy) return; setBusy(true); setLoadError("");
          try {
            const updated = creating ? await post<LearningNote>("/notes", { title, content, course_id: courseId || null, request_id: request.current }) : await api<LearningNote>(`/notes/${selected!.id}`, { method: "PATCH", body: JSON.stringify({ title, content, expected_version: selected!.version }) });
            setSelected(updated); setEditing(false); setCreating(false); setNotice("笔记已保存。"); reload();
          } catch (e) { setLoadError(errorMessage(e)); } finally { setBusy(false); }
        }}><label>笔记标题<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required /></label><label>内容<textarea rows={16} value={content} onChange={(event) => setContent(event.target.value)} maxLength={100000} required /></label><div className="learning-actions"><button type="button" className="button" disabled={busy} onClick={() => { setEditing(false); setCreating(false); }}>取消</button><button className="button primary" disabled={busy || !title.trim() || !content.trim()}>{busy ? "正在保存…" : "保存笔记"}</button></div></form> : selected ? <><div className="learning-note-heading"><div><h3>{selected.title}</h3><span className="muted small">v{selected.version} · {formatDate(selected.updated_at)}</span></div><div className="learning-actions"><button className="icon-button" title="编辑笔记" aria-label="编辑笔记" disabled={busy} onClick={edit}><Pencil size={16} /></button><a className="icon-button" title="导出 Markdown" aria-label="导出 Markdown" href={`/api/notes/${selected.id}/export`} download><Download size={16} /></a></div></div><Markdown>{selected.content}</Markdown><Citations items={selected.sources || []} /></> : <Empty title="记下这一刻的理解" description="保存的回答会保留引用，笔记可以继续编辑和导出。" />}
      </div>
    </div>
  </Modal>;
}

export function TeachingPanel({ courseId, nodeId, revision, blocked = false, getSession, onRequest, onChanged }: {
  courseId: string; nodeId?: string; revision?: unknown; blocked?: boolean; getSession?: () => Promise<{ id: string }>; onRequest?: (prompt: string) => void; onChanged?: () => void;
}) {
  const { data: state, setData, error, reload } = useResource<TeachingState>(`/courses/${encodeURIComponent(courseId)}/teaching${nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : ""}`);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [deferOpen, setDeferOpen] = useState(false);
  const [reason, setReason] = useState("");
  const lastRevision = useRef(revision);
  useEffect(() => { if (lastRevision.current !== revision) { lastRevision.current = revision; reload(); } }, [revision, reload]);
  useEffect(() => { setNotice(""); setActionError(""); }, [courseId, nodeId]);
  async function feedback(effect: "helped" | "not_helped") {
    if (!getSession || busy || blocked) return;
    const content = effect === "helped" ? "这段讲解对我有帮助。" : "我还没理解，请换一种讲法，结合一个不同的例子。";
    setBusy(true); setActionError(""); setNotice("");
    try {
      const session = await getSession();
      setData(await post<TeachingState>(`/tutor/sessions/${session.id}/feedback`, { content, effect, request_id: uid() }));
      setNotice(effect === "helped" ? "反馈已记录。" : "反馈已记录，换一种方式继续。"); onChanged?.();
      if (effect === "not_helped") onRequest?.(content);
    } catch (e) { setActionError(errorMessage(e)); } finally { setBusy(false); }
  }
  const action = state?.next_action;
  const targetNode = nodeId || state?.node_id || action?.node_id;
  const prompt = action?.prompt || `${action?.label || "继续学习"}。请结合我的实际学习记录安排下一步。`;
  const href = action?.node_id && !action?.prompt ? `/courses/${courseId}/learn/${action.node_id}` : `/chat?course=${encodeURIComponent(courseId)}&prompt=${encodeURIComponent(prompt)}`;
  const navigateToNode = !!action?.node_id && ["next_node", "prerequisite"].includes(action.kind);
  const phaseLabels: Record<string, string> = { explain: "理解讲解", practice: "练习检验", remediate: "纠正误解", verify: "独立验证", mastered: "已掌握", deferred: "已暂缓" };
  if (!state && !error) return null;
  return <section className="learning-next-action" aria-label="教学下一步">
    {action ? <><div className="learning-next-heading"><h3>{action.label || "继续学习"}</h3>{navigateToNode ? <Link className="text-button" href={`/courses/${courseId}/learn/${action.node_id}`}>继续 <ArrowRight size={14} /></Link> : onRequest ? <button className="text-button" disabled={busy || blocked} onClick={() => onRequest(prompt)}>继续 <ArrowRight size={14} /></button> : <Link className="text-button" href={href}>继续 <ArrowRight size={14} /></Link>}</div>{action.reason && <p>{action.reason}</p>}</> : <h3>学习安排</h3>}
    {state?.node_title && <p className="learning-teaching-status">{state.node_title}{typeof state.mastery === "number" && ` · 掌握度 ${Math.round(state.mastery)}%`}{state.phase && phaseLabels[state.phase] && ` · ${phaseLabels[state.phase]}`}</p>}
    {error && <ErrorBox message={error} retry={reload} />}
    <div className="learning-feedback-actions">{getSession && <><button className="text-button" disabled={busy || blocked} onClick={() => void feedback("not_helped")}>换种讲法</button><button className="text-button" disabled={busy || blocked} onClick={() => void feedback("helped")}>有帮助</button></>}{targetNode && <button className="text-button" disabled={busy || blocked} onClick={() => setDeferOpen(true)}>暂缓这一节</button>}{notice && <span className="learning-status" role="status">{notice}</span>}</div>
    {actionError && <ErrorBox message={actionError} />}
    {deferOpen && <Modal title="暂缓这一节" onClose={() => setDeferOpen(false)}><form className="form-stack" onSubmit={async (event) => {
      event.preventDefault(); setBusy(true); setActionError("");
      try { setData(await post<TeachingState>(`/nodes/${targetNode}/defer`, { reason: reason || "我想先暂缓这一节。", days: 1 })); setDeferOpen(false); setNotice("已暂缓到明天，可随时回来继续。"); onChanged?.(); }
      catch (e) { setActionError(errorMessage(e)); } finally { setBusy(false); }
    }}><p className="muted">明天再继续这一节，当前掌握度保持原样。</p><label>暂缓原因（可选）<textarea rows={3} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如：想先复习前置知识" /></label>{actionError && <ErrorBox message={actionError} />}<button className="button primary" disabled={busy}>{busy ? "正在保存…" : "暂缓到明天"}</button></form></Modal>}
  </section>;
}

export function QuestionDispute({ exerciseId, disabled, onRequest }: { exerciseId: string; disabled?: boolean; onRequest: (prompt: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  return <><button type="button" className="text-button question-dispute" disabled={disabled} onClick={() => setOpen(true)}><Flag size={13} />题目有疑问</button>{open && <Modal title="请 Atlas 检查这道题" onClose={() => setOpen(false)}><div className="form-stack"><p className="muted">说明题干、选项或评分哪里有疑问。Atlas 会先给出检查结果和修复预览。</p><label>问题说明<textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} maxLength={2000} required placeholder="例如：这个选项在题目给定条件下也成立。" /></label><button type="button" className="button primary" disabled={disabled || !reason.trim()} onClick={() => {
    onRequest(`请检查题目（exercise_id: ${exerciseId}）的争议：${reason.trim()}。请结合原题、我的作答和课程资料核查，先生成修复预览，等待我确认后再应用。未作答时请不要透露答案。`); setOpen(false);
  }}>请 Atlas 检查</button></div></Modal>}</>;
}
