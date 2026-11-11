"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, Check, Loader2, NotebookPen, Paperclip, Plus, RefreshCw, Square } from "lucide-react";
import { api, post, uid, useResource } from "@/lib/api";
import type { AgentTask, Attempt, Citation, Course, CourseDetail, Exercise } from "@/lib/types";
import { useAtlas } from "./atlas-app";
import { Citations, ErrorBox, Loading, Markdown } from "./ui";
import { NotesDrawer, QuestionDispute, SaveTurnNote, TeachingPanel, type LearningNote } from "./learning-panels";
import { AgentRunButton } from "./agent-run-dialog";
import { SolveResult, solvePayload, type PublicSolveResult } from "./solve-result";
import "./tutor.css";

type Mode = "outline" | "study" | "review";
type Capability = "tutor" | "solve";
type Session = { id: string; title: string; course_id: string | null; node_id: string | null; mode: Mode; updated_at: string };
type Change = { path: string; before: unknown; after: unknown };
type Action = { action_id: string; title: string; changes?: Change[]; question?: string; kind?: string; exercise_id?: string };
type CapabilityResult = { capability: string; status: string; outcome?: string; verified_steps?: number; reasoned_steps?: number; limitations?: string[] };
type Turn = { id: string; session_id: string; request_id: string; input: string; output: string; status: string; error?: string | null; pending_action?: Action | null; last_seq: number; capability?: Capability; result?: CapabilityResult | PublicSolveResult | null; events?: TutorEvent[] };
type TutorEvent = { seq: number; type: string; payload: Record<string, unknown> };
type TutorAttempt = Attempt & { voided?: boolean };
type RepairReceipt = { exercise_id: string; action_id?: string; revision?: number; mode?: string; voided?: boolean; attempts?: { id: string; score: number; passed: boolean; feedback: string; voided?: boolean }[] };
type KnownRepair = RepairReceipt & { previousAttempts: TutorAttempt[] | null };
type SessionDetail = Session & { turns: Turn[] };
const running = (turn?: Turn) => !!turn && ["queued", "running"].includes(turn.status);
const terminal = (status: string) => ["completed", "failed", "cancelled"].includes(status);
const labels: Record<string, string> = { queued: "等待开始", running: "正在思考", waiting_input: "等待你的回答", waiting_confirmation: "等待确认变更", failed: "本轮未完成", cancelled: "已停止" };
const modes: [Mode, string][] = [["study", "学习"], ["outline", "规划路径"], ["review", "复习"]];
function readStore<T>(key: string, fallback: T): T {
  try { return JSON.parse(sessionStorage.getItem(key) || "null") ?? fallback; } catch { return fallback; }
}
function saveStore(key: string, value: unknown) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Storage may be disabled. The server remains authoritative. */ }
}
function message(error: unknown) { return error instanceof Error ? error.message : "请求未完成，请重试。"; }

export function TutorScreen() { return <Tutor />; }

export function Tutor({ courseId: fixedCourse, nodeId: fixedNode, onChanged, incomingRequest }: { courseId?: string; nodeId?: string; onChanged?: () => void; incomingRequest?: { id: string; content: string } | null }) {
  const { user } = useAtlas();
  const scopeKey = `atlas:tutor:${user.id}:${fixedCourse || "all"}:${fixedNode || "all"}`;
  const { data: courses, error: coursesError, reload: reloadCourses } = useResource<Course[]>("/courses");
  const [courseId, setCourseId] = useState(fixedCourse || "");
  const [nodeId, setNodeId] = useState(fixedNode || "");
  const [mode, setMode] = useState<Mode>("study");
  const [capability, setCapability] = useState<Capability>("tutor");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const draftRef = useRef(draft); draftRef.current = draft;
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [importTask, setImportTask] = useState<AgentTask | null>(null);
  const [uploading, setUploading] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [savedNote, setSavedNote] = useState<LearningNote | null>(null);
  const [teachingRevision, setTeachingRevision] = useState(0);
  const [repairs, setRepairs] = useState<Record<string, KnownRepair>>({});
  const seenRepairs = useRef(new Set<string>());
  const receivedRequest = useRef("");
  const mounted = useRef(true);
  const loadVersion = useRef(0);
  const sessionRef = useRef<Session | null>(null);
  const sendLock = useRef(false);
  const pendingRequest = useRef<{ content: string; capability: Capability; sessionId: string; id: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const { data: course, error: courseError, reload: reloadCourse } = useResource<CourseDetail>(courseId ? `/courses/${courseId}` : null);
  const { data: attempts, error: attemptsError, reload: reloadAttempts } = useResource<TutorAttempt[]>(courseId ? `/attempts?course_id=${courseId}&include_voided=true` : null);
  const attemptsRef = useRef(attempts); attemptsRef.current = attempts;
  const activeTurn = [...turns].reverse().find((turn) => !terminal(turn.status));
  const blocked = busy || uploading || running(activeTurn) || activeTurn?.status === "waiting_confirmation";
  const newDraftKey = (course: string, node: string, nextMode: Mode, nextCapability: Capability) => `${scopeKey}:draft:new:${course}:${node}:${nextMode}${nextCapability === "solve" ? ":solve" : ""}`;
  const draftKey = session ? `${scopeKey}:draft:${session.id}` : newDraftKey(courseId, nodeId, mode, capability);

  useEffect(() => { mounted.current = true; setImportTask(readStore(`${scopeKey}:import`, null)); return () => { mounted.current = false; }; }, [scopeKey]);
  const selectSession = useCallback(async (id: string) => {
    const version = ++loadVersion.current;
    setLoading(true); setError(""); setTurns([]); setRepairs({}); seenRepairs.current.clear();
    try {
      const detail = await api<SessionDetail>(`/tutor/sessions/${encodeURIComponent(id)}`);
      if (!mounted.current || version !== loadVersion.current) return;
      if ((fixedCourse && detail.course_id !== fixedCourse) || (fixedNode && detail.node_id !== fixedNode)) throw new Error("这段对话不属于当前学习范围，请从原课程打开。");
      sessionRef.current = detail; setSession(detail); setTurns(detail.turns);
      setCourseId(detail.course_id || ""); setNodeId(detail.node_id || ""); setMode(detail.mode);
      const savedCapability = readStore<Capability | null>(`${scopeKey}:capability:${detail.id}`, null);
      setCapability(savedCapability === "solve" || (!savedCapability && detail.turns.at(-1)?.capability === "solve") ? "solve" : "tutor");
      pendingRequest.current = null;
      saveStore(`${scopeKey}:selected`, detail.id);
      setDraft(readStore(`${scopeKey}:draft:${detail.id}`, ""));
    } catch (e) { if (mounted.current && version === loadVersion.current) setError(message(e)); }
    finally { if (mounted.current && version === loadVersion.current) setLoading(false); }
  }, [scopeKey, fixedCourse, fixedNode]);

  useEffect(() => {
    let disposed = false;
    const query = new URLSearchParams();
    if (fixedCourse) query.set("course_id", fixedCourse);
    if (fixedNode) query.set("node_id", fixedNode);
    void api<Session[]>(`/tutor/sessions?${query}`).then(async (items) => {
      if (disposed) return;
      setSessions(items);
      const params = new URLSearchParams(window.location.search);
      const requestedSession = params.get("session");
      if (requestedSession) {
        // Resolve through the owned-session API; errors stay visible and never select another conversation.
        sessionRef.current = null; setSession(null); setDraft(""); pendingRequest.current = null;
        await selectSession(requestedSession);
        return;
      }
      const requestedCourse = !fixedCourse && params.get("course");
      const prompt = params.get("prompt");
      if (requestedCourse || prompt) {
        const nextCourse = requestedCourse || fixedCourse || "";
        const nextMode = params.get("mode") === "study" ? "study" : prompt ? "outline" : "study";
        startNew(nextCourse, fixedNode || "", nextMode, "tutor");
        setDraft(prompt || "");
        saveStore(`${scopeKey}:draft:new:${nextCourse}:${fixedNode || ""}:${nextMode}`, prompt || "");
        window.history.replaceState(window.history.state, "", window.location.pathname);
        return;
      }
      const saved = readStore<string | null>(`${scopeKey}:selected`, null);
      if (saved === "new") {
        const context = readStore(`${scopeKey}:new`, { courseId: fixedCourse || "", nodeId: fixedNode || "", mode: "study" as Mode, capability: "tutor" as Capability });
        startNew(context.courseId, context.nodeId, context.mode, context.capability || "tutor"); return;
      }
      const selected = items.find((item) => item.id === saved) || items[0];
      if (selected) await selectSession(selected.id);
      else { startNew(fixedCourse || "", fixedNode || "", "study", "tutor"); }
    }).catch((e) => { if (!disposed) { setError(message(e)); setLoading(false); } });
    return () => { disposed = true; ++loadVersion.current; };
  }, [scopeKey, fixedCourse, fixedNode, selectSession, reload]);

  useEffect(() => {
    if (!importTask || terminal(importTask.status) || importTask.status === "succeeded") return;
    let active = true;
    const timer = setInterval(() => {
      void api<AgentTask>(`/tasks/${importTask.id}`).then((task) => {
        if (!active) return;
        setImportTask(task);
        saveStore(`${scopeKey}:import`, task);
        if (task.status === "succeeded") { reloadCourse(); onChanged?.(); }
      }).catch((e) => { if (active) setError(message(e)); });
    }, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [importTask?.id, importTask?.status, reloadCourse, onChanged]);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns.length, session?.id]);

  const updateTurn = useCallback((updated: Turn) => {
    if (sessionRef.current?.id !== updated.session_id) return;
    setTurns((previous) => previous.map((turn) => turn.id === updated.id ? updated : turn));
  }, []);
  const changed = useCallback(() => {
    setTeachingRevision((value) => value + 1);
    reloadCourse(); reloadCourses(); reloadAttempts(); onChanged?.();
    const id = sessionRef.current?.id;
    if (id) void api<SessionDetail>(`/tutor/sessions/${id}`).then((detail) => {
      if (!mounted.current || sessionRef.current?.id !== id) return;
      sessionRef.current = detail; setSession(detail);
      setSessions((items) => items.map((item) => item.id === id ? detail : item));
      setCourseId(detail.course_id || ""); setNodeId(detail.node_id || ""); setMode(detail.mode);
    }).catch((e) => { if (mounted.current && sessionRef.current?.id === id) setError(message(e)); });
  }, [reloadCourse, reloadCourses, reloadAttempts, onChanged]);
  const repaired = useCallback((receipt: RepairReceipt) => {
    if (!receipt.exercise_id) return;
    const key = `${receipt.exercise_id}:${receipt.revision ?? receipt.action_id ?? "repair"}`;
    if (seenRepairs.current.has(key)) return;
    seenRepairs.current.add(key);
    setRepairs((previous) => {
      if ((previous[receipt.exercise_id]?.revision || 0) > (receipt.revision || 0)) return previous;
      return { ...previous, [receipt.exercise_id]: { ...receipt, previousAttempts: attemptsRef.current } };
    });
    changed();
  }, [changed]);
  function startNew(nextCourse = courseId, nextNode = nodeId, nextMode = mode, nextCapability: Capability = capability, preservedDraft?: string) {
    ++loadVersion.current; sessionRef.current = null; setSession(null); setTurns([]); setLoading(false); setError("");
    setCourseId(nextCourse); setNodeId(nextNode); setMode(nextMode); setCapability(nextCapability);
    setRepairs({}); seenRepairs.current.clear();
    saveStore(`${scopeKey}:selected`, "new");
    saveStore(`${scopeKey}:new`, { courseId: nextCourse, nodeId: nextNode, mode: nextMode, capability: nextCapability });
    const nextKey = newDraftKey(nextCourse, nextNode, nextMode, nextCapability);
    const nextDraft = preservedDraft ?? readStore(nextKey, "");
    setDraft(nextDraft); saveStore(nextKey, nextDraft);
    pendingRequest.current = null;
  }
  async function ensureSession() {
    if (sessionRef.current) return sessionRef.current;
    const created = await post<Session>("/tutor/sessions", { course_id: courseId || null, node_id: nodeId || null, mode });
    sessionRef.current = created;
    saveStore(`${scopeKey}:draft:${created.id}`, draft);
    saveStore(`${scopeKey}:capability:${created.id}`, capability);
    if (mounted.current) { setSession(created); setSessions((items) => [created, ...items]); saveStore(`${scopeKey}:selected`, created.id); }
    return created;
  }
  async function send(content = draft) {
    const text = content.trim();
    if (!text || sendLock.current || blocked) return;
    sendLock.current = true; setBusy(true); setError("");
    const turnCapability = activeTurn?.status === "waiting_input" ? activeTurn.capability || "tutor" : capability;
    const requestSessionId = sessionRef.current?.id || "new";
    if (pendingRequest.current?.content !== text || pendingRequest.current.capability !== turnCapability || pendingRequest.current.sessionId !== requestSessionId) pendingRequest.current = { content: text, capability: turnCapability, sessionId: requestSessionId, id: uid() };
    try {
      const selected = await ensureSession();
      pendingRequest.current.sessionId = selected.id;
      const turn = activeTurn?.status === "waiting_input"
        ? await post<Turn>(`/tutor/turns/${activeTurn.id}/respond`, { content: text })
        : await post<Turn>(`/tutor/sessions/${selected.id}/turns`, { content: text, request_id: pendingRequest.current.id, ...(turnCapability === "solve" ? { capability: turnCapability } : {}) });
      saveStore(draftKey, ""); pendingRequest.current = null;
      saveStore(`${scopeKey}:draft:${selected.id}`, "");
      if (mounted.current && sessionRef.current?.id === selected.id) {
        setDraft(""); setTurns((items) => items.some((item) => item.id === turn.id) ? items.map((item) => item.id === turn.id ? turn : item) : [...items, turn]);
      }
    } catch (e) { if (mounted.current) setError(message(e)); }
    finally { sendLock.current = false; if (mounted.current) setBusy(false); }
  }
  async function answer(exercise: Exercise, answer: string, requestId: string, expectedSessionId: string) {
    if (sessionRef.current?.id !== expectedSessionId) throw new Error("会话已切换，请回到原对话提交答案。");
    if (!sessionRef.current || sendLock.current || running(activeTurn) || activeTurn?.status === "waiting_confirmation") throw new Error("请先等待当前回答完成。");
    const selected = sessionRef.current; sendLock.current = true; setBusy(true);
    try {
      const turn = await post<Turn>(`/tutor/sessions/${selected.id}/answers`, { exercise_id: exercise.id, answer, request_id: requestId });
      if (mounted.current && sessionRef.current?.id === selected.id) setTurns((items) => items.some((item) => item.id === turn.id) ? items.map((item) => item.id === turn.id ? turn : item) : [...items.map((item) => item.status === "waiting_input" ? { ...item, status: "completed", pending_action: null } : item), turn]);
      changed();
      return turn;
    } finally { sendLock.current = false; if (mounted.current) setBusy(false); }
  }
  async function upload(file: File) {
    setUploading(true); setError(""); const body = new FormData(); body.set("file", file);
    const selectedCourse = courseId;
    try {
      const task = await api<AgentTask>(selectedCourse ? `/courses/${selectedCourse}/imports` : "/tutor/imports", { method: "POST", body });
      setImportTask(task); saveStore(`${scopeKey}:import`, task);
      reloadCourses();
      if (!selectedCourse && task.course_id) {
        const preservedDraft = draftRef.current;
        startNew(task.course_id, "", "outline", "tutor");
        setDraft(preservedDraft);
        saveStore(`${scopeKey}:draft:new:${task.course_id}::outline`, preservedDraft);
      }
    }
    catch (e) { setError(message(e)); } finally { setUploading(false); }
  }
  function planImportedCourse() {
    if (!importTask?.course_id) return;
    const prompt = "请基于刚导入的课程资料，为这门课程规划学习路径。";
    const preservedDraft = draft.trim();
    const nextDraft = preservedDraft.includes(prompt) ? draft : preservedDraft ? `${draft}\n\n${prompt}` : prompt;
    startNew(importTask.course_id, "", "outline", "tutor");
    setDraft(nextDraft);
    saveStore(`${scopeKey}:draft:new:${importTask.course_id}::outline`, nextDraft);
  }
  useEffect(() => {
    if (!incomingRequest || receivedRequest.current === incomingRequest.id || loading || blocked) return;
    receivedRequest.current = incomingRequest.id;
    void send(incomingRequest.content);
  }, [incomingRequest, loading, blocked]);
  return (
    <section className="atlas-tutor" aria-label="Atlas 学习对话">
      <header className="atlas-tutor-header">
        <h1>{fixedNode ? "学习对话" : "Atlas"}</h1>
        <label className="tutor-session-select"><span className="sr-only">切换会话</span><select aria-label="切换会话" value={session?.id || ""} disabled={busy || loading} onChange={(e) => e.target.value ? void selectSession(e.target.value) : startNew()}><option value="">新对话</option>{sessions.map((item) => <option key={item.id} value={item.id}>{item.title || "学习对话"}</option>)}</select></label>
        <button className="icon-button" aria-label="新建对话" title="新建对话" disabled={busy} onClick={() => startNew()}><Plus size={19} /></button>
        <button className="icon-button" aria-label={courseId ? "课程笔记" : "个人笔记"} title="学习笔记" onClick={() => { setSavedNote(null); setNotesOpen(true); }}><NotebookPen size={18} /></button>
      </header>
      <div className="atlas-tutor-context">
        <label><span className="sr-only">课程</span><select aria-label="对话课程" value={courseId} disabled={!!fixedCourse || busy} onChange={(e) => startNew(e.target.value, "")}><option value="">全部学习 · 未指定课程</option>{courses?.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        {courseId && <label><span className="sr-only">知识节点</span><select aria-label="对话知识节点" value={nodeId} disabled={!!fixedNode || busy} onChange={(e) => startNew(courseId, e.target.value)}><option value="">整门课程</option>{course?.nodes.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
        <div className="atlas-tutor-modes" aria-label="对话模式">{modes.map(([value, label]) => <button key={value} type="button" aria-pressed={capability === "tutor" && mode === value} disabled={busy || loading} onClick={() => { if (mode !== value || capability !== "tutor") startNew(courseId, nodeId, value, "tutor", draft); }}>{label}</button>)}<button type="button" aria-pressed={capability === "solve"} disabled={busy || loading} onClick={() => { if (capability !== "solve") startNew(courseId, nodeId, mode, "solve", draft); }}>解题</button></div>
      </div>
      <div className="atlas-tutor-thread">
        <div className="atlas-tutor-measure">
          {loading ? <Loading label="正在恢复学习对话…" /> : !turns.length && <div className="atlas-tutor-welcome"><h2>{fixedNode ? "从这一节，继续理解。" : "今天想弄懂什么？"}</h2><p>{capability === "solve" ? "发来题目，Atlas 会分步求解，并展示适用步骤的计算结果和校验记录。无需先选择课程。" : "提出问题或学习目标，Atlas 会结合课程和资料，带你讲解、练习与复习。"}</p><div>{(capability === "solve" ? ["解方程 x² - 5x + 6 = 0，并检查结果", "帮我梳理这道题的解题步骤"] : mode === "outline" ? ["结合课程资料，为我检查学习路径", "我想从零学习一个新主题"] : mode === "review" ? ["带我复习当前最需要巩固的知识", "根据最近的错题，帮我做一次复习"] : ["从我当前的学习进度继续", "给我一道练习，检验一下理解"]).map((text) => <button key={text} disabled={blocked} onClick={() => { setDraft(text); saveStore(draftKey, text); }}>{text}</button>)}</div></div>}
          {turns.map((turn) => <TutorTurn key={turn.id} turn={turn} storageKey={`${scopeKey}:events:${turn.id}`} blocked={blocked} attempts={attempts || []} attemptsReady={!!attempts} repairs={repairs} gradingTurns={turns} courseId={courseId} onUpdate={updateTurn} onChanged={changed} onRepaired={repaired} onAnswer={(exercise, value, requestId) => answer(exercise, value, requestId, turn.session_id)} onRetry={(text) => void send(text)} onNoteSaved={(note) => { setSavedNote(note); setNotesOpen(true); }} />)}
          {courseId && capability === "tutor" && !loading && <TeachingPanel key={`${courseId}:${nodeId}`} courseId={courseId} nodeId={nodeId} revision={teachingRevision} blocked={blocked} getSession={ensureSession} onRequest={(prompt) => void send(prompt)} onChanged={changed} />}
          {importTask && <div className="atlas-tutor-import" role="status"><Paperclip size={16} /><span>{importTask.message || "资料导入"} · {importTask.status === "succeeded" ? "已完成" : labels[importTask.status] || importTask.status}{importTask.error && `：${importTask.error}`}</span><Link href={`/tasks?task=${importTask.id}`}>查看任务</Link></div>}
          {importTask?.status === "succeeded" && importTask.course_id === courseId && course && course.nodes.length === 0 && <button type="button" className="button" disabled={blocked || uploading} onClick={planImportedCourse}>基于资料规划学习路径</button>}
          {(error || coursesError || courseError || attemptsError) && <ErrorBox message={error || coursesError || courseError || attemptsError} retry={() => { if (coursesError) reloadCourses(); else if (courseError) reloadCourse(); else if (attemptsError) reloadAttempts(); else setReload((value) => value + 1); }} />}
          <div ref={bottom} />
        </div>
      </div>
      <form className="atlas-tutor-compose" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <div className="atlas-tutor-input">
          <textarea aria-label="向 Atlas 提问" rows={2} maxLength={12000} placeholder={activeTurn?.status === "waiting_input" ? "写下你的回答…" : capability === "solve" ? "输入题目、已知条件和想求的结果…" : "提出问题、学习目标，或告诉我哪里没想明白…"} value={draft} onChange={(e) => { setDraft(e.target.value); saveStore(draftKey, e.target.value); }} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
          <div className="atlas-tutor-input-actions">
            <input ref={fileInput} type="file" hidden accept=".pdf,.txt,.md,.docx" onChange={(e) => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ""; }} />
            <button type="button" className="icon-button" disabled={uploading || busy || loading} aria-label={courseId ? "导入课程资料" : "上传教材并创建课程"} title={courseId ? "导入课程资料" : "上传教材并创建课程"} onClick={() => fileInput.current?.click()}>{uploading ? <Loader2 className="spin" size={18} /> : <Paperclip size={18} />}</button>
            <span>{activeTurn && !terminal(activeTurn.status) ? labels[activeTurn.status] : "Enter 发送 · Shift + Enter 换行"}</span>
            {running(activeTurn) ? <button type="button" className="atlas-tutor-send" aria-label="停止当前回答" onClick={async () => { try { updateTurn(await post<Turn>(`/tutor/turns/${activeTurn!.id}/cancel`)); } catch (e) { setError(message(e)); } }}><Square size={15} /></button> : <button className="atlas-tutor-send" aria-label="发送消息" disabled={blocked || loading || !draft.trim()}>{busy ? <Loader2 size={17} className="spin" /> : <ArrowUp size={19} />}</button>}
          </div>
        </div>
      </form>
      {notesOpen && <NotesDrawer key={courseId || "personal"} courseId={courseId || undefined} initialNote={savedNote} onClose={() => setNotesOpen(false)} />}
    </section>
  );
}

function TutorTurn({ turn, storageKey, blocked, attempts, attemptsReady, repairs, gradingTurns, courseId, onUpdate, onChanged, onRepaired, onAnswer, onRetry, onNoteSaved }: { turn: Turn; storageKey: string; blocked: boolean; attempts: TutorAttempt[]; attemptsReady: boolean; repairs: Record<string, KnownRepair>; gradingTurns: Turn[]; courseId: string; onUpdate: (turn: Turn) => void; onChanged: () => void; onRepaired: (receipt: RepairReceipt) => void; onAnswer: (exercise: Exercise, answer: string, requestId: string) => Promise<Turn>; onRetry: (text: string) => void; onNoteSaved: (note: LearningNote) => void }) {
  const [events, setEvents] = useState<TutorEvent[]>([]);
  const [streamError, setStreamError] = useState("");
  const [retry, setRetry] = useState(0);
  const [responding, setResponding] = useState(false);
  const latestTurn = useRef(turn); latestTurn.current = turn;
  const answerElement = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const thread = answerElement.current?.closest(".atlas-tutor-thread");
    if (thread && running(turn) && thread.scrollHeight - thread.scrollTop - thread.clientHeight < 200) thread.scrollTop = thread.scrollHeight;
  }, [events, turn.status]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const saved = readStore<TutorEvent[]>(storageKey, []);
    const cached = saved.filter((event) => typeof event.seq === "number" && typeof event.type === "string");
    const collected: TutorEvent[] = [...new Map([...cached, ...(turn.events || [])].map((event) => [event.seq, event])).values()].sort((a, b) => a.seq - b.seq);
    collected.filter((event) => event.type === "question_repaired").forEach((event) => onRepaired(event.payload as unknown as RepairReceipt));
    let seq = readStore<number>(`${storageKey}:cursor`, cached.reduce((last, event) => Math.max(last, event.seq), 0));
    setEvents([...collected]); setStreamError("");
    if (terminal(turn.status) || (collected.length && seq >= turn.last_seq && !running(turn))) return () => { disposed = true; controller.abort(); };
    let failures = 0;
    const connect = async () => {
      if (disposed) return;
      try {
        const response = await fetch(`/api/tutor/turns/${turn.id}/events?after_seq=${seq}`, { credentials: "include", cache: "no-store", signal: controller.signal, headers: { Accept: "text/event-stream" } });
        if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "暂时无法恢复回答"); }
        if (!response.body) throw new Error("浏览器没有收到回答，请重连。");
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
        const consume = (frame: string) => {
          const lines = frame.split(/\r?\n/); const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (!data) return;
          const event = JSON.parse(data) as TutorEvent;
          if (!event.type) event.type = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
          if (event.seq <= seq) return;
          if (!Number.isFinite(event.seq)) throw new Error("未收到有效的回答记录，请重连。");
          seq = event.seq;
          const index = collected.findIndex((item) => item.seq === event.seq);
          if (index >= 0) collected[index] = event; else collected.push(event);
          collected.sort((a, b) => a.seq - b.seq);
          saveStore(storageKey, collected); saveStore(`${storageKey}:cursor`, seq); setEvents([...collected]); failures = 0; setStreamError("");
          if (event.type === "done" && event.payload.turn) { onUpdate(event.payload.turn as Turn); onChanged(); }
          if (event.type === "status") {
            const status = typeof event.payload.status === "string" ? event.payload.status : null;
            if (status && latestTurn.current.status !== status) onUpdate({ ...latestTurn.current, status });
          }
          if (event.type === "confirmation") onUpdate({ ...latestTurn.current, status: "waiting_confirmation", pending_action: event.payload as unknown as Action });
          if (event.type === "question_repaired") onRepaired(event.payload as unknown as RepairReceipt);
          if (event.type === "input_required") onUpdate({ ...latestTurn.current, status: "waiting_input" });
        };
        while (!disposed) {
          const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
          let boundary;
          while ((boundary = /\r?\n\r?\n/.exec(buffer))) { consume(buffer.slice(0, boundary.index)); buffer = buffer.slice(boundary.index + boundary[0].length); }
          if (done) { if (buffer.trim()) consume(buffer); break; }
        }
        if (disposed) return;
        const fresh = await api<Turn>(`/tutor/turns/${turn.id}`, { signal: controller.signal }); onUpdate(fresh);
        if (["queued", "running"].includes(fresh.status)) { setStreamError("连接已断开，正在恢复已保存的回答…"); timer = setTimeout(connect, 1200); }
      } catch (e) {
        if (disposed || controller.signal.aborted) return;
        failures += 1; setStreamError(`${message(e)}${failures < 4 ? "，正在重新连接…" : ""}`);
        if (failures < 4) timer = setTimeout(connect, Math.min(failures * 1500, 5000));
      }
    };
    void connect();
    return () => { disposed = true; controller.abort(); if (timer) clearTimeout(timer); };
  }, [turn.id, turn.status, turn.events, storageKey, retry, onUpdate, onChanged, onRepaired]);

  let text = ""; let hasText = false;
  const responses: { offset: number; content: string; seq: number }[] = [];
  for (const event of events) {
    if (event.type === "content_reset") { text = String(event.payload.text || ""); hasText = true; }
    else if (event.type === "content") { text += String(event.payload.text || ""); hasText = true; }
    else if (event.type === "user_response") responses.push({ offset: typeof event.payload.output_offset === "number" ? event.payload.output_offset : text.length, content: String(event.payload.content || ""), seq: event.seq });
  }
  if (terminal(turn.status) && turn.output) text = turn.output;
  else if (!hasText) text = turn.output || "";
  const tools = events.filter((event) => event.type === "tool_start");
  const cited = events.filter((event) => event.type === "citations").flatMap((event) => (event.payload.citations || []) as Citation[]);
  const questions = events.filter((event) => event.type === "question").flatMap((event) => (event.payload.exercises || []) as Exercise[]).filter((exercise, index, all) => all.findIndex((item) => item.id === exercise.id) === index);
  const assessments = events.filter((event) => event.type === "assessment").map((event) => {
    const original = event.payload as unknown as TutorAttempt;
    const latest = attempts.find((attempt) => attempt.id === original.id);
    const receipt = repairs[original.exercise_id];
    const hint = receipt?.attempts?.find((attempt) => attempt.id === original.id);
    const fresh = attemptsReady && !!latest && attempts !== receipt?.previousAttempts;
    return { ...original, ...(latest || {}), ...(!fresh && hint ? hint : {}), correct_answer: receipt && !fresh ? "" : (latest || original).correct_answer, refreshing: !!receipt && !fresh, pendingScore: !!receipt && !fresh && !hint };
  });
  const isVoided = (exerciseId: string) => repairs[exerciseId]?.mode === "void" || repairs[exerciseId]?.voided === true || attempts.some((attempt) => attempt.exercise_id === exerciseId && attempt.voided);
  const solveResults = events.map((event) => solvePayload(event.payload.result) || (event.type.startsWith("solve") ? solvePayload(event.payload) : null)).filter((result): result is PublicSolveResult => !!result);
  const latestSolve = solvePayload(turn.result) || [...solveResults].reverse().find((result) => result.plan);
  const solveEvidence = solveResults.flatMap((result) => [...(result.executions || []), ...(result.execution ? [result.execution] : [])]);
  const validation = events.filter((event) => event.type === "tool_result").map((event) => (event.payload.result as Record<string, unknown> | undefined)?.validation).filter(Boolean).at(-1);
  const input = events.filter((event) => event.type === "input_required").at(-1);
  const confirmation = turn.pending_action || events.filter((event) => event.type === "confirmation").at(-1)?.payload as Action | undefined;
  const hideRepairAnswer = confirmation?.kind === "question_repair" && !attempts.some((attempt) => attempt.exercise_id === confirmation.exercise_id);
  const eventError = events.filter((event) => event.type === "error").at(-1)?.payload.detail;
  async function confirm(approved: boolean) {
    if (!confirmation) return;
    setResponding(true); setStreamError("");
    try { onUpdate(await post<Turn>(`/tutor/turns/${turn.id}/respond`, { approved, action_id: confirmation.action_id })); onChanged(); }
    catch (e) { setStreamError(message(e)); } finally { setResponding(false); }
  }
  return <article className="atlas-tutor-turn">
    <div className="atlas-tutor-user"><span>你</span><Markdown>{turn.input}</Markdown></div>
    <div className="atlas-tutor-answer" ref={answerElement}><span className="atlas-tutor-author">Atlas</span>
      {tools.length > 0 && <details className="atlas-tutor-tools"><summary>{running(turn) ? "正在处理任务" : "查看处理过程"} · {tools.length} 项</summary>{tools.map((tool) => { const result = events.find((event) => event.type === "tool_result" && event.payload.call_id === tool.payload.call_id); return <details key={tool.seq}><summary>{result ? <Check size={13} /> : <Loader2 size={13} className={running(turn) ? "spin" : ""} />}<span>{toolName(String(tool.payload.tool || ""))}</span></summary><ToolResult payload={result?.payload.result} /></details>; })}<AgentRunButton kind="agent" runId={turn.id} /></details>}
      {latestSolve && <SolveResult result={latestSolve} evidence={solveEvidence} />}
      {turn.result && "capability" in turn.result && turn.result.capability === "solve" && <p className="atlas-tutor-validation">{turn.result.verified_steps ?? 0} 步执行校验 · {turn.result.reasoned_steps ?? 0} 步推理说明。校验仅覆盖列出的检查。</p>}
      {text || responses.length ? <>{responses.map((response, index) => <div key={response.seq}>{text.slice(index ? responses[index - 1].offset : 0, response.offset) && <Markdown>{text.slice(index ? responses[index - 1].offset : 0, response.offset)}</Markdown>}<div className="atlas-tutor-user"><span>你的补充回答</span><Markdown>{response.content}</Markdown></div></div>)}{text.slice(responses.at(-1)?.offset || 0) && <Markdown>{text.slice(responses.at(-1)?.offset || 0)}</Markdown>}</> : running(turn) && <div className="atlas-tutor-thinking" role="status"><Loader2 size={15} className="spin" />{labels[turn.status]}</div>}
      <Citations items={cited.filter((citation, index, all) => all.findIndex((item) => item.id === citation.id && item.title === citation.title) === index)} />
      {questions.length > 0 && <PracticeValidation value={validation} />}
      {questions.map((exercise) => <TutorExercise key={exercise.id} exercise={exercise} initialAttempt={attempts.find((attempt) => attempt.exercise_id === exercise.id)} attemptsReady={attemptsReady} gradingTurns={gradingTurns} courseId={courseId} disabled={blocked || turn.status === "cancelled"} voided={!!(exercise as Exercise & { voided?: boolean }).voided || isVoided(exercise.id)} storageKey={`${storageKey}:exercise:${exercise.id}`} onAnswer={onAnswer} onDispute={onRetry} />)}
      {assessments.map((attempt, index) => <div className={`atlas-tutor-assessment${attempt.voided || isVoided(attempt.exercise_id) ? " assessment-voided" : ""}`} key={attempt.id || index}>{attempt.voided || isVoided(attempt.exercise_id) ? <><strong>已作废，不计掌握度</strong><p className="muted small">原始作答已保留，这道题不再参与学习判定。</p></> : <><strong>{attempt.pendingScore ? "正在更新评分" : attempt.passed ? "理解已巩固" : "继续巩固这一点"}{!attempt.pendingScore && <span>{Math.round(attempt.score)} / 100</span>}</strong>{!attempt.pendingScore && <Markdown>{attempt.feedback || "评分已保存。"}</Markdown>}{attempt.refreshing && <p className="muted small" role="status">修复已应用，正在读取更新后的答案与解析…</p>}{attempt.correct_answer && <details><summary>参考答案与解释</summary><Markdown>{attempt.correct_answer}</Markdown></details>}</>}</div>)}
      {turn.status === "waiting_input" && !!(input?.payload.question || turn.pending_action?.question) && <div className="atlas-tutor-prompt"><Markdown>{String(input?.payload.question || turn.pending_action?.question)}</Markdown><span>在下方输入框作答，或提交题卡。</span></div>}
      {turn.status === "waiting_confirmation" && confirmation && <section className="atlas-tutor-confirmation"><h3>{confirmation.title || "确认学习变更"}</h3><p>以下是即将写入的变更。接受后应用这些变更。</p><div className="atlas-tutor-changes">{confirmation.changes?.length ? confirmation.changes.map((change, index) => <div key={index}><strong>{change.path}</strong><div><ChangeValue label="当前" value={previewValue(change.before, change.path, hideRepairAnswer)} /><ChangeValue label="调整后" value={previewValue(change.after, change.path, hideRepairAnswer)} /></div></div>) : <p>尚未收到精确变更，暂时无法接受。请拒绝后重新请求预览。</p>}</div><div className="atlas-tutor-confirm-actions"><button className="button" disabled={responding} onClick={() => void confirm(false)}>拒绝</button><button className="button primary" disabled={responding || !confirmation.changes?.length} onClick={() => void confirm(true)}>{responding ? "正在处理…" : "接受这些变更"}</button></div></section>}
      {turn.status === "completed" && !!text.trim() && <SaveTurnNote turnId={turn.id} onSaved={onNoteSaved} />}
      {!!(turn.error || (turn.status === "failed" && eventError)) && <ErrorBox message={turn.error || String(eventError)} />}
      {streamError && <ErrorBox message={streamError} retry={() => setRetry((value) => value + 1)} />}
      {["failed", "cancelled"].includes(turn.status) && <button className="text-button atlas-tutor-retry" disabled={blocked} onClick={() => onRetry(turn.input)}><RefreshCw size={14} />重新提问</button>}
      {!tools.length && <AgentRunButton kind="agent" runId={turn.id} />}
    </div>
  </article>;
}

function toolName(name: string) {
  const names: Record<string, string> = { search_materials: "检索课程资料", retrieve_materials: "检索课程资料", research_topic: "查找学习证据", generate_practice: "准备练习", prepare_lesson: "准备讲解", get_learning_state: "查看学习进度", get_recent_attempts: "回顾最近作答", list_due_reviews: "安排复习", propose_path_change: "准备路径变更预览", propose_question_repair: "检查题目并准备修复预览", get_teaching_state: "安排学习下一步", record_feedback: "记录学习反馈", defer_node: "暂缓当前知识点", rate_review: "更新复习安排", solve_plan: "制定解题计划", solve_status: "查看解题进度", python_check: "运行计算与检查", solve_finish_step: "记录步骤结果", solve_finish: "汇总解题结果" };
  return names[name] || "处理课程学习任务";
}
function ToolResult({ payload }: { payload: unknown }) {
  if (!payload || typeof payload !== "object") return <p className="muted small">已请求，结果将显示在回答中。</p>;
  const result = payload as Record<string, unknown>;
  const solve = solvePayload(payload);
  if (solve) return <SolveResult result={solve} detailed />;
  const task = result.task as { id?: string; message?: string } | undefined;
  const summary = result.summary || result.message || task?.message;
  return <div className="atlas-tutor-tool-result">{typeof summary === "string" && <Markdown>{summary}</Markdown>}<PracticeValidation value={result.validation} />{task?.id && <Link href={`/tasks?task=${task.id}`}>查看任务进度</Link>}{!summary && !task?.id && <p className="muted small">已完成，相关内容已用于本轮回答。</p>}</div>;
}
function PracticeValidation({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return null;
  const receipt = value as Record<string, unknown>;
  if (receipt.method !== "model_assisted" || receipt.status !== "passed") return null;
  return <p className="atlas-tutor-validation">生成时已通过模型辅助核对重点、答案与依据{typeof receipt.checked_count === "number" ? ` · ${receipt.checked_count} 道` : ""}{receipt.repaired === true ? " · 已修正后核对" : ""}{typeof receipt.focused_topic === "string" && <> · {receipt.focused_topic}</>}</p>;
}
function ChangeValue({ label, value }: { label: string; value: unknown }) {
  return <div><span>{label}</span>{value === null || value === undefined ? <p>无</p> : typeof value === "object" ? <pre>{JSON.stringify(value, null, 2)}</pre> : <p>{String(value)}</p>}</div>;
}
function previewValue(value: unknown, path: string, hideAnswers: boolean): unknown {
  if (!hideAnswers) return value;
  if (/answer|rubric|explanation|答案|解析|评分标准/i.test(path)) return "作答后可查看答案内容";
  if (Array.isArray(value)) return value.map((item) => previewValue(item, "", true));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, previewValue(item, key, true)]));
  return value;
}
type ExerciseSubmission = { answer: string; request: string; phase?: "pending" | "completed" | "failed"; gradingTurnId?: string; courseId?: string; submitted?: boolean };
function TutorExercise({ exercise, disabled, voided, storageKey, initialAttempt, attemptsReady, gradingTurns, courseId, onAnswer, onDispute }: { exercise: Exercise; disabled: boolean; voided: boolean; storageKey: string; initialAttempt?: TutorAttempt; attemptsReady: boolean; gradingTurns: Turn[]; courseId: string; onAnswer: (exercise: Exercise, answer: string, requestId: string) => Promise<Turn>; onDispute: (prompt: string) => void }) {
  const [answer, setAnswer] = useState("");
  const [phase, setPhase] = useState<"editing" | "pending" | "completed" | "failed">("editing");
  const [gradingTurnId, setGradingTurnId] = useState("");
  const [gradingCourseId, setGradingCourseId] = useState(courseId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const request = useRef("");
  const values = useRef({ answer, courseId: gradingCourseId });
  values.current = { answer, courseId: gradingCourseId };
  const actualAttempt = useRef(initialAttempt); actualAttempt.current = initialAttempt;

  useEffect(() => {
    const saved = readStore<ExerciseSubmission | null>(storageKey, null);
    if (!saved) return;
    setAnswer(saved.answer); request.current = saved.request;
    setGradingCourseId(saved.courseId || courseId);
    const savedTurn = saved.gradingTurnId || gradingTurns.find((turn) => turn.request_id === saved.request)?.id || "";
    setGradingTurnId(savedTurn);
    // Older caches marked queued submissions as complete. Only server evidence can complete a card.
    setPhase(savedTurn || saved.submitted || saved.phase === "completed" ? "pending" : saved.phase || "editing");
  }, [storageKey]);
  useEffect(() => {
    if (initialAttempt) { setAnswer(initialAttempt.answer); setPhase("completed"); setError(""); }
  }, [initialAttempt?.id]);
  useEffect(() => { if (voided) { setPhase("completed"); setError(""); } }, [voided]);
  useEffect(() => {
    if (phase === "pending" && !gradingTurnId && attemptsReady && !initialAttempt && !busy) {
      setPhase("failed"); request.current = uid();
      setError("尚未找到评分记录，可以重新提交答案。");
      saveStore(storageKey, { ...values.current, phase: "failed", request: request.current });
    }
  }, [phase, gradingTurnId, attemptsReady, initialAttempt?.id, busy, storageKey]);

  useEffect(() => {
    if (!gradingTurnId || phase !== "pending" || initialAttempt || voided) return;
    const controller = new AbortController(); let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined; let failures = 0;
    const persist = (next: "completed" | "failed") => {
      setPhase(next);
      saveStore(storageKey, { ...values.current, phase: next, request: request.current, gradingTurnId });
    };
    const check = async () => {
      try {
        const turn = await api<Turn>(`/tutor/turns/${gradingTurnId}`, { signal: controller.signal });
        if (disposed) return;
        const assessed = turn.events?.some((event) => event.type === "assessment" && event.payload.exercise_id === exercise.id);
        if (assessed || actualAttempt.current) { persist("completed"); setError(""); return; }
        if (terminal(turn.status)) {
          // A worker can save an Attempt before emitting its assessment event. Check the durable record before allowing retry.
          const attempts = await api<TutorAttempt[]>(`/attempts?course_id=${encodeURIComponent(values.current.courseId)}&include_voided=true`, { signal: controller.signal });
          if (disposed) return;
          if (attempts.some((attempt) => attempt.exercise_id === exercise.id)) { persist("completed"); setError(""); return; }
          request.current = uid(); persist("failed");
          setError(turn.status === "cancelled" ? "评分已停止，尚未保存作答记录。可以重新提交。" : "本轮未完成评分，可以重新提交答案。");
          return;
        }
        failures = 0; setError(""); timer = setTimeout(check, 2500);
      } catch (e) {
        if (disposed || controller.signal.aborted) return;
        failures += 1; setError("暂时无法确认评分状态，请重试查询。");
        if (failures < 4) timer = setTimeout(check, 3000);
      }
    };
    void check();
    return () => { disposed = true; controller.abort(); if (timer) clearTimeout(timer); };
  }, [gradingTurnId, phase, initialAttempt?.id, exercise.id, storageKey, revision, voided]);

  const locked = disabled || voided || busy || !attemptsReady || phase === "pending" || phase === "completed";
  function change(value: string) {
    setAnswer(value); request.current = uid(); setPhase("editing"); setError("");
    saveStore(storageKey, { answer: value, phase: "editing", request: request.current, courseId });
  }
  return <form className="atlas-tutor-exercise" onSubmit={async (event) => {
    event.preventDefault(); if (locked || !answer.trim()) return;
    setBusy(true); setError(""); if (!request.current) request.current = uid();
    try {
      const turn = await onAnswer(exercise, answer, request.current);
      setGradingTurnId(turn.id); setGradingCourseId(courseId); setPhase("pending");
      saveStore(storageKey, { answer, phase: "pending", request: request.current, gradingTurnId: turn.id, courseId });
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }}>
    <span className="muted small">{exercise.type === "choice" ? "选择题" : "用自己的话解释"}</span>
    {voided && <p className="muted small" role="status">已作废，不计掌握度</p>}
    <Markdown>{exercise.prompt}</Markdown>
    {exercise.type === "choice" ? <div className="atlas-tutor-options">{exercise.options.map((option, index) => <label key={index}><input type="radio" name={`tutor-answer-${exercise.id}`} checked={answer === option} disabled={locked} onChange={() => change(option)} /><span>{option}</span></label>)}</div> : <textarea aria-label="练习答案" rows={3} maxLength={10000} value={answer} disabled={locked} placeholder="写下你的理解…" onChange={(e) => change(e.target.value)} required />}
    {error && <ErrorBox message={error} retry={phase === "pending" ? () => setRevision((value) => value + 1) : undefined} />}
    <button className="button" disabled={locked || !answer.trim()}>{voided ? "题目已作废" : busy ? "正在提交…" : phase === "completed" ? "已提交，评分见后续反馈" : phase === "pending" ? "已提交，正在等待评分…" : phase === "failed" ? "重新提交答案" : "提交答案"}</button>
    <QuestionDispute exerciseId={exercise.id} disabled={disabled || voided || busy || phase === "pending"} onRequest={onDispute} />
  </form>;
}
