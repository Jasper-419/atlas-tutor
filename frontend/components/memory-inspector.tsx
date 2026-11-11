"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, formatDate, post, uid, useResource } from "@/lib/api";
import type { Course, Memory } from "@/lib/types";
import { ErrorBox, Loading, Modal } from "./ui";
import "./memory-inspector.css";

type Evidence = { kind: string; status: string; label: string; quote?: string; url?: string | null; turn_id?: string; seq?: number; attempt_id?: string; exercise_id?: string; note_id?: string; note_version?: number; score?: number };
type Revision = { revision: number; content: string; category: string; status: string; created_at: string; origin?: string; evidence?: Evidence[] };
export type MemoryDetail = { memory: Memory; evidence: Evidence[]; history: Revision[] };
type Profile = { status: "empty" | "pending" | "ready" | "stale" | "failed"; updated_at?: string; groups: { label: string; claims: { quote: string; memory_id: string; revision: number }[] }[] };
type RecordAudit = { checked: number; valid: number; partial: number; unavailable: number; legacy: number };
type RecordRun = {
  status: "empty" | "pending" | "succeeded" | "failed";
  counts?: { chat: number; note: number; practice: number; created: number; merged: number; suppressed: number; changed: number };
  audit?: RecordAudit;
  has_more?: boolean;
  message?: string;
};

export function memoryStatus(status?: string) {
  return ({ active: "有效", forgotten: "已忘记", superseded: "已被更新", stale: "来源已失效", invalidated: "来源已失效", source_missing: "来源缺失", source_changed: "来源已变化", content_changed: "原始内容已变化", legacy_unverified: "历史记录，待你确认", missing: "来源缺失", unavailable: "来源不可用", valid: "来源有效", current: "来源有效", legacy: "历史记录，未保留来源", unknown: "来源状态未知", manual: "手动记录" } as Record<string, string>)[status || ""] || (status ? "暂不用于讲解" : "历史记录");
}

function sourceHref(url?: string | null) {
  // Only application routes are source links; provider URLs or untrusted schemes are never opened.
  return url && /^\/(?!\/)/.test(url) ? url : null;
}

export function RecordMemory({ courses, onChanged }: { courses: Course[]; onChanged: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState<"organize" | "audit" | null>(null);
  const [error, setError] = useState("");
  const [audit, setAudit] = useState<RecordAudit | null>(null);
  const request = useRef<string | null>(null);
  const suffix = scope ? `?course_id=${encodeURIComponent(scope)}` : "";
  const { data: run, loading, error: loadError, setData, reload } = useResource<RecordRun>(
    open ? "/me/memory/organize" + suffix : null,
  );

  async function organize() {
    setBusy("organize");
    setError("");
    if (!request.current) request.current = uid();
    try {
      const result = await post<RecordRun>("/me/memory/organize", { course_id: scope || null, request_id: request.current });
      setData(result);
      setAudit(null);
      request.current = null;
      if (result.status === "succeeded") onChanged("学习记录已整理。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "整理未完成。");
      reload();
    } finally {
      setBusy(null);
    }
  }

  async function checkSources() {
    setBusy("audit");
    setError("");
    try {
      setAudit(await api<RecordAudit>("/me/memory/audit" + suffix));
    } catch (e) {
      setError(e instanceof Error ? e.message : "来源暂时无法核查。");
    } finally {
      setBusy(null);
    }
  }

  const counts = run?.counts;
  const checked = audit || run?.audit;
  return (
    <details className="memory-profile" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>整理学习记录</summary>
      <div className="memory-profile-body">
        <p className="settings-hint">按需整理新增或更新的聊天、笔记和练习，保留可核对的原文与作答来源。</p>
        <div className="memory-profile-toolbar">
          <label>整理范围<select aria-label="学习记录整理范围" value={scope} disabled={!!busy} onChange={(event) => {
            setScope(event.target.value);
            setAudit(null);
            setError("");
            request.current = null;
          }}>
            <option value="">全部学习记录</option>
            {courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
          </select></label>
          <button className="button" disabled={!!busy || loading || run?.status === "pending"} onClick={() => void organize()}>
            {busy === "organize" ? "正在整理…" : run?.has_more ? "整理下一批" : "整理新记录"}
          </button>
        </div>
        <button className="text-button" disabled={!!busy} onClick={() => void checkSources()}>{busy === "audit" ? "正在核查…" : "核查来源"}</button>
        {(error || loadError || run?.status === "failed") && <ErrorBox message={error || loadError || run?.message || "上次整理未完成。"} />}
        {!busy && run?.status === "pending" && <p className="settings-hint">整理正在进行。 <button className="text-button" onClick={reload}>刷新状态</button></p>}
        {counts && <p className="settings-hint" role="status">
          本批聊天 {counts.chat} · 笔记 {counts.note} · 练习 {counts.practice} · 新增 {counts.created} · 合并 {counts.merged}
          {counts.suppressed > 0 && ` · 跳过已停用 ${counts.suppressed}`}
          {counts.changed > 0 && ` · 来源变化 ${counts.changed}`}
        </p>}
        {checked && <p className="settings-hint" role="status">
          已核查 {checked.checked} 条 · 有效 {checked.valid} · 部分来源有效 {checked.partial} · 失效 {checked.unavailable} · 待确认 {checked.legacy}
        </p>}
      </div>
    </details>
  );
}

export function MemoryInspector({ memory, onClose, onEdit, onChanged }: { memory: Memory; onClose: () => void; onEdit: (memory: Memory) => void; onChanged: (message: string) => void }) {
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [error, setError] = useState("");
  const [legacy, setLegacy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError(""); setLegacy(false);
    void api<MemoryDetail>(`/me/memories/${encodeURIComponent(memory.id)}`, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setDetail(value); })
      .catch((e) => { if (!controller.signal.aborted) { if (e instanceof ApiError && e.status === 404) setLegacy(true); else setError(e instanceof Error ? e.message : "暂时无法读取来源。"); } });
    return () => controller.abort();
  }, [memory.id, revision]);
  const current = detail?.memory || memory;
  async function remove() {
    setPending(true); setError("");
    try {
      await api(`/me/memories/${encodeURIComponent(memory.id)}`, { method: "DELETE" });
      onChanged("记忆及其修订记录已永久删除。"); onClose();
    } catch (e) { setError(e instanceof Error ? e.message : "删除未完成。"); }
    finally { setPending(false); }
  }
  async function confirm() {
    setPending(true); setError("");
    try {
      await api(`/me/memories/${encodeURIComponent(memory.id)}`, { method: "PATCH", body: JSON.stringify({ content: current.content, expected_revision: current.revision }) });
      onChanged("已确认这条记忆，可用于后续学习。"); setRevision((value) => value + 1);
    } catch (e) { setError(e instanceof ApiError && e.status === 409 ? "这条记忆已被更新，请刷新并核对最新内容。" : e instanceof Error ? e.message : "确认未完成。"); }
    finally { setPending(false); }
  }
  return <Modal title="来源与历史" className="memory-inspector-modal" onClose={onClose}>
    <div className="memory-inspector">
      <div className="memory-inspector-current"><span className="memory-state">{memoryStatus(current.status)}</span><p>{current.content}</p><span className="small muted">{current.origin === "manual" ? "手动记录" : current.origin === "legacy" ? "历史记录" : "学习记忆"}{current.revision ? ` · 第 ${current.revision} 版` : ""}</span></div>
      {current.origin === "legacy" && current.status === "active" && typeof current.revision === "number" && <div><p className="settings-hint">这条历史记忆缺少可核对的来源，暂不用于讲解。确认内容仍符合你的情况后，可以继续使用。</p><button className="button" disabled={pending} onClick={() => void confirm()}>确认这条记忆</button></div>}
      {error && <ErrorBox message={error} retry={() => setRevision((value) => value + 1)} />}
      {!detail && !error && !legacy && <Loading label="正在读取来源与修订记录…" />}
      {legacy && <p className="settings-hint">当前服务尚未提供这条记忆的来源与修订记录。</p>}
      {detail && <>
        <section className="memory-detail-section"><h3>来源</h3>{detail.evidence.length ? detail.evidence.map((evidence, index) => <div className="memory-evidence" key={`${evidence.kind}:${evidence.turn_id || evidence.attempt_id || "manual"}:${index}`}>
          <div className="memory-detail-heading"><strong>{evidence.label || "学习记录"}{evidence.note_version && ` · 第 ${evidence.note_version} 版`}{typeof evidence.score === "number" && ` · ${evidence.score} 分`}</strong><span>{memoryStatus(evidence.status)}</span></div>
          {evidence.quote && <blockquote>{evidence.quote}</blockquote>}
          {sourceHref(evidence.url) && <a className="text-button" href={sourceHref(evidence.url)!}>{evidence.kind === "note" ? "下载原笔记" : evidence.kind === "assessment" ? "打开所属课程" : "查看原始记录"}</a>}
        </div>) : <p className="settings-hint">{current.origin === "manual" ? "这条内容由你手动记录。" : "历史记录未保留可核对的来源。"}</p>}</section>
        <section className="memory-detail-section"><h3>修订历史</h3>{detail.history.length ? <ol className="memory-history">{detail.history.map((item) => <li key={item.revision}><div className="memory-detail-heading"><strong>第 {item.revision} 版 · {memoryStatus(item.status)}</strong><time>{formatDate(item.created_at)}</time></div><p>{item.content}</p>{!!item.evidence?.length && <details className="memory-history-evidence"><summary>当时的来源</summary>{item.evidence.map((evidence, index) => <div className="memory-evidence" key={index}><div className="memory-detail-heading"><strong>{evidence.label}</strong><span>{memoryStatus(evidence.status)}</span></div>{evidence.quote && <blockquote>{evidence.quote}</blockquote>}{sourceHref(evidence.url) && <a className="text-button" href={sourceHref(evidence.url)!}>查看原始记录</a>}</div>)}</details>}</li>)}</ol> : <p className="settings-hint">尚无修订记录。</p>}</section>
      </>}
      <div className="memory-inspector-actions"><button className="button" disabled={pending} onClick={() => { onClose(); onEdit(current); }}>纠正记忆</button><button className="text-button memory-delete" disabled={pending} onClick={() => void remove()}>{pending ? "正在删除…" : "永久删除"}</button></div>
      <p className="settings-hint">永久删除会同时移除这条记忆的来源关联与修订历史。</p>
    </div>
  </Modal>;
}

export function MemoryProfile({ courses, refreshVersion, onInspect }: { courses: Course[]; refreshVersion: number; onInspect: (id: string) => void }) {
  const [scope, setScope] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [unsupported, setUnsupported] = useState(false);
  const [pending, setPending] = useState(false);
  const [revision, setRevision] = useState(0);
  const request = useRef<{ scope: string; id: string } | null>(null);
  const scopeVersion = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    ++scopeVersion.current; request.current = null;
    setProfile(null); setError(""); setUnsupported(false); setPending(false);
    void api<Profile>(`/me/memory/profile${scope ? `?course_id=${encodeURIComponent(scope)}` : ""}`, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setProfile(value); })
      .catch((e) => { if (!controller.signal.aborted) { if (e instanceof ApiError && e.status === 404) setUnsupported(true); else setError(e instanceof Error ? e.message : "暂时无法读取学习画像。"); } });
    return () => { controller.abort(); ++scopeVersion.current; };
  }, [scope, refreshVersion, revision]);
  async function consolidate() {
    const version = scopeVersion.current;
    if (!request.current || request.current.scope !== scope) request.current = { scope, id: uid() };
    setPending(true); setError("");
    try {
      const value = await post<Profile>("/me/memory/consolidate", { course_id: scope || null, request_id: request.current.id });
      if (version === scopeVersion.current) { setProfile(value); request.current = null; }
    } catch (e) { if (version === scopeVersion.current) setError(e instanceof Error ? e.message : "整理未完成，请重试。"); }
    finally { if (version === scopeVersion.current) setPending(false); }
  }
  if (unsupported) return null;
  return <details className="memory-profile"><summary>学习画像<span>{profile?.status === "ready" ? "已整理" : profile?.status === "stale" ? "需要重新整理" : "按需整理"}</span></summary>
    <div className="memory-profile-body">
      <div className="memory-profile-toolbar"><label>适用范围<select aria-label="画像适用范围" value={scope} onChange={(event) => setScope(event.target.value)} disabled={pending}><option value="">个人学习档案</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label><button className="button" disabled={pending || !profile} onClick={() => void consolidate()}>{pending ? "正在整理…" : profile?.status === "ready" ? "重新整理" : "整理学习画像"}</button></div>
      <p className="settings-hint">根据当前有效记忆整理，只有你点击整理时才会更新。</p>
      {profile?.status === "pending" && <button className="text-button" onClick={() => setRevision((value) => value + 1)}>重新读取</button>}
      {error && <ErrorBox message={error} retry={() => setRevision((value) => value + 1)} />}
      {!profile && !error ? <Loading label="正在读取学习画像…" /> : profile?.status === "stale" ? <p className="memory-profile-notice">记忆或来源已变化，原画像已过期。请重新整理后查看。</p> : profile?.status === "empty" ? <p className="settings-hint">尚未整理出学习画像。添加有效记忆后可以在此整理。</p> : profile?.status === "pending" ? <p className="settings-hint">画像正在整理中。稍后可以重新读取。</p> : profile?.status === "failed" ? <p className="settings-hint">上次整理未完成，可以重新整理。</p> : profile?.status === "ready" && <div className="memory-profile-sections">{profile.groups.map((group) => <section key={group.label}><h3>{group.label}</h3><ul>{group.claims.map((item, index) => <li key={`${item.memory_id}:${item.revision}:${index}`}><span>{item.quote}</span><button className="text-button" onClick={() => onInspect(item.memory_id)}>查看依据</button></li>)}</ul></section>)}{profile.updated_at && <p className="small muted">整理于 {formatDate(profile.updated_at)}</p>}</div>}
    </div>
  </details>;
}
