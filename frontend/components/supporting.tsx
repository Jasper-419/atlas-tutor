"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Plus,
  Trash2,
  Pencil,
  RefreshCw,
  Square,
  Loader2,
  Check,
  Workflow,
  AlertTriangle,
} from "lucide-react";
import { api, ApiError, post, useResource, formatDate } from "@/lib/api";
import type { Memory, Course, AgentTask } from "@/lib/types";
import { useAtlas } from "./atlas-app";
import { AgentRunButton } from "./agent-run-dialog";
import { MemoryInspector, MemoryProfile, RecordMemory, memoryStatus, type MemoryDetail } from "./memory-inspector";
import {
  PageTitle,
  Loading,
  ErrorBox,
  Empty,
  Modal,
  Status,
  Progress,
  Markdown,
} from "./ui";

export function MemoriesScreen({ embedded = false }: { embedded?: boolean }) {
  const [includeHistory, setIncludeHistory] = useState(false);
  const {
      data: memories,
      error,
      loading,
      reload,
    } = useResource<Memory[]>(`/me/memories${includeHistory ? "?include_history=true" : ""}`),
    { data: courses } = useResource<Course[]>("/courses"),
    { notify: notifyApp } = useAtlas();
  const [modal, setModal] = useState<Memory | "new" | null>(null),
    [filter, setFilter] = useState("all"),
    [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState(""),
    [feedback, setFeedback] = useState(""),
    [inspected, setInspected] = useState<Memory | null>(null),
    [profileVersion, setProfileVersion] = useState(0),
    [pendingMemory, setPendingMemory] = useState(""),
    [conflict, setConflict] = useState(false),
    [latestContent, setLatestContent] = useState<string | null>(null);
  const notify = (message: string) =>
    embedded ? setFeedback(message) : notifyApp(message);
  const labels: Record<string, string> = {
    preference: "学习偏好",
    goal: "学习目标",
    weakness: "薄弱知识",
    insight: "理解与反馈",
    fact: "学习事实",
    misconception: "具体误解",
    note: "学习笔记",
    practice_record: "练习记录",
  };
  const shown = (memories || []).filter((m) =>
    (includeHistory || !m.status || m.status === "active") && (filter === "all" || m.category === filter));
  function changed(message: string) { reload(); setProfileVersion((value) => value + 1); notify(message); }
  function edit(memory: Memory | "new") { setModal(memory); setActionError(""); setConflict(false); setLatestContent(null); }
  async function forget(memory: Memory) {
    setPendingMemory(memory.id);
    try { await post(`/me/memories/${encodeURIComponent(memory.id)}/forget`, { expected_revision: memory.revision }); changed("已忘记这条记忆，不再用于后续讲解。历史记录仍可查看。"); }
    catch (e) { notify(e instanceof ApiError && e.status === 409 ? "记忆已被更新，请重新读取后再操作。" : (e as Error).message); reload(); }
    finally { setPendingMemory(""); }
  }
  return (
    <>
      {embedded ? (
        <div className="settings-memory-toolbar">
          <p className="settings-hint">查看记忆的来源，也可以纠正或让 Atlas 忘记。</p>
          <button
            className="button"
            onClick={() => {
              edit("new");
              setFeedback("");
            }}
          >
            <Plus size={15} />
            添加记忆
          </button>
        </div>
      ) : (
        <PageTitle
          title="学习记忆"
          description="查看学习记忆的来源，随时纠正或让 Atlas 忘记。"
        >
          <button
            className="button primary"
            onClick={() => {
              edit("new");
            }}
          >
            <Plus size={16} />
            添加学习记忆
          </button>
        </PageTitle>
      )}
      {embedded && feedback && (
        <p className="settings-feedback" role="status">
          {feedback}
        </p>
      )}
      <RecordMemory courses={courses || []} onChanged={changed} />
      <MemoryProfile courses={courses || []} refreshVersion={profileVersion} onInspect={(id) => {
        const memory = memories?.find((item) => item.id === id);
        if (memory) setInspected(memory);
        else void api<MemoryDetail>(`/me/memories/${encodeURIComponent(id)}`).then((detail) => setInspected(detail.memory)).catch((e) => notify((e as Error).message));
      }} />
      <div className="filter-row">
        <div className="tabs">
          {[
            ["all", "全部"],
            ["preference", "偏好"],
            ["weakness", "薄弱点"],
            ["goal", "目标"],
          ].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setFilter(v)}
              className={filter === v ? "active" : ""}
            >
              {l}
            </button>
          ))}
        </div>
        <label className="memory-history-toggle"><input type="checkbox" checked={includeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} />查看历史</label>
        <span className="small muted">{shown.length} 条记忆</span>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} retry={reload} />
      ) : shown.length ? (
        <div className="memory-grid">
          {shown.map((m) => (
            <article className="panel memory-card" key={m.id}>
              <div className="section-heading">
                <span className="memory-category">
                  {labels[m.category] || m.category}
                </span>
                <div className="row-actions">
                  <button
                    className="icon-button"
                    aria-label="编辑记忆"
                    onClick={() => {
                      edit(m);
                    }}
                  >
                    <Pencil size={14} />
                  </button>
                  {m.status && m.status !== "active" && <span className="memory-state">{memoryStatus(m.status)}</span>}
                </div>
              </div>
              <p>{m.content}</p>
              {m.source_status && m.source_status !== "valid" && <span className="memory-state">{memoryStatus(m.source_status)}{m.source_status === "legacy_unverified" ? "后用于讲解" : ""}</span>}
              <div className="memory-card-controls"><button className="text-button" onClick={() => setInspected(m)}>来源与历史{typeof m.evidence_count === "number" ? ` · ${m.evidence_count}` : ""}</button>{typeof m.revision === "number" && m.status !== "forgotten" && <button className="text-button" disabled={!!pendingMemory} onClick={() => void forget(m)}>{pendingMemory === m.id ? "正在忘记…" : "忘记"}</button>}</div>
              <div className="memory-footer">
                <span>
                  {m.course_id
                    ? courses?.find((c) => c.id === m.course_id)?.title ||
                      "课程记忆"
                    : "个人学习档案"}
                </span>
                <time>{formatDate(m.updated_at, true)}</time>
              </div>
            </article>
          ))}
        </div>
      ) : embedded ? (
        <p className="settings-hint">还没有学习记忆。</p>
      ) : (
        <Empty
          title="让 Atlas 更了解你的学习方式"
          description="例如“我喜欢先看具体例子，再理解原理”。练习中的薄弱点也会逐渐形成记忆。"
        >
          <button className="button" onClick={() => edit("new")}>
            添加第一条记忆 <Plus size={14} />
          </button>
        </Empty>
      )}
      {modal && (
        <Modal
          title={modal === "new" ? "记住一点关于你的事" : "修正这条学习记忆"}
          onClose={() => setModal(null)}
        >
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              setBusy(true);
              setActionError("");
              try {
                if (modal === "new")
                  await post("/me/memories", {
                    content: f.get("content"),
                    category: f.get("category"),
                    course_id: f.get("course_id") || null,
                  });
                else
                  await api(`/me/memories/${modal.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ content: f.get("content"), ...(typeof modal.revision === "number" ? { expected_revision: modal.revision } : {}) }),
                  });
                setModal(null);
                changed("学习记忆已保存。");
              } catch (e) {
                const conflicted = e instanceof ApiError && e.status === 409;
                setConflict(conflicted);
                setActionError(conflicted ? "这条记忆已被更新，你的修改尚未保存。读取最新内容并核对后，再次保存。" : (e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {modal === "new" && (
              <div className="form-two-col">
                <label>
                  记忆类型
                  <select name="category">
                    <option value="preference">学习偏好</option>
                    <option value="goal">学习目标</option>
                    <option value="weakness">薄弱知识</option>
                    <option value="insight">理解与反馈</option>
                  </select>
                </label>
                <label>
                  适用范围
                  <select name="course_id">
                    <option value="">所有课程</option>
                    {courses?.map((c) => (
                      <option value={c.id} key={c.id}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            <label>
              记忆内容
              <textarea
                name="content"
                rows={5}
                defaultValue={modal === "new" ? "" : modal.content}
                required
                minLength={2}
                maxLength={3000}
                placeholder="例如：我有 Python 基础，希望讲解中多用实际代码示例。"
              />
            </label>
            {latestContent !== null && <div className="memory-conflict-current"><strong>当前已保存的内容</strong><p>{latestContent}</p></div>}
            {actionError && <ErrorBox message={actionError} />}
            {conflict && modal !== "new" && <button type="button" className="text-button" disabled={busy} onClick={async () => {
              setBusy(true);
              try { const detail = await api<MemoryDetail>(`/me/memories/${encodeURIComponent(modal.id)}`); setModal(detail.memory); setLatestContent(detail.memory.content); setConflict(false); setActionError("已读取最新版本。请核对上方内容与自己的修改，再保存。"); reload(); }
              catch (e) { setActionError((e as Error).message); }
              finally { setBusy(false); }
            }}>读取最新版本</button>}
            <button className="button primary" disabled={busy}>
              保存学习记忆
            </button>
          </form>
        </Modal>
      )}
      {inspected && <MemoryInspector key={inspected.id} memory={inspected} onClose={() => setInspected(null)} onEdit={edit} onChanged={changed} />}
    </>
  );
}

export function TasksScreen() {
  const {
      data: tasks,
      error,
      loading,
      reload,
    } = useResource<AgentTask[]>("/tasks", 4000),
    { notify } = useAtlas(),
    [selected, setSelected] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    setSelected(new URLSearchParams(window.location.search).get("task") || "");
  }, []);
  const task = tasks?.find((t) => t.id === selected) || tasks?.[0],
    kindLabels: Record<string, string> = {
      plan: "课程规划",
      research: "资料研究",
      replan: "路径调整",
      ingest: "资料导入",
      reindex: "资料索引重建",
      knowledge_index: "课程检索索引",
      knowledge_page: "PDF 页级索引",
    };
  async function action(id: string, kind: string) {
    setBusy(true);
    try {
      await post(`/tasks/${id}/${kind}`);
      reload();
      notify(kind === "cancel" ? "已请求取消任务。" : "任务已加入重试队列。");
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageTitle
        title="Agent 任务"
        description="每一步研究与规划，都有进度、来源和可追溯的执行记录。"
      >
        <button className="button" onClick={reload}>
          <RefreshCw size={15} />
          刷新
        </button>
      </PageTitle>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} retry={reload} />
      ) : !tasks?.length ? (
        <Empty
          title="还没有进行中的探索"
          description="创建课程、调整路径或发起资料研究后，执行过程会记录在这里。"
        >
          <Link href="/courses/new" className="button">
            创建学习目标 <ArrowRight size={15} />
          </Link>
        </Empty>
      ) : (
        <div className="tasks-layout">
          <div className="task-list">
            {tasks.map((t) => (
              <button
                key={t.id}
                className={`task-list-row ${task?.id === t.id ? "selected" : ""}`}
                onClick={() => setSelected(t.id)}
              >
                <span className="task-kind">
                  <Workflow size={16} />
                  {kindLabels[t.kind] || t.kind}
                </span>
                <strong>{t.message || "正在等待执行"}</strong>
                <div>
                  <Status value={t.status} />
                  <time>{formatDate(t.created_at, true)}</time>
                </div>
              </button>
            ))}
          </div>
          {task && (
            <section className="panel task-detail">
              <div className="section-heading">
                <h2>{kindLabels[task.kind] || task.kind}</h2>
                <Status value={task.status} />
              </div>
              <p className="task-message">{task.message}</p>
              <div className="task-progress-label">
                <span>执行进度</span>
                <span>{Math.round(task.progress)}%</span>
              </div>
              <Progress value={task.progress} />
              {task.error && <ErrorBox message={task.error} />}
              <div className="task-actions">
                <AgentRunButton kind="workflow" runId={task.id} />
                {["queued", "running"].includes(task.status) && (
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() => void action(task.id, "cancel")}
                  >
                    <Square size={13} />
                    取消任务
                  </button>
                )}
                {["failed", "cancelled"].includes(task.status) && (
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() => void action(task.id, "retry")}
                  >
                    <RefreshCw size={14} />
                    重试任务
                  </button>
                )}
                {task.course_id && (
                  <Link
                    href={`/courses/${task.course_id}`}
                    className="text-link"
                  >
                    返回课程 <ArrowUpRight size={14} />
                  </Link>
                )}
              </div>
              <div className="trace-heading">
                <h3>执行轨迹</h3>
                <span className="small muted">
                  {task.traces?.length || 0} 个步骤
                </span>
              </div>
              <div className="trace-list">
                {task.traces?.length ? (
                  task.traces.map((tr, i) => (
                    <details className="trace-row" key={tr.id}>
                      <summary>
                        <span className={`trace-dot trace-${tr.status}`}>
                          {tr.status === "succeeded" ||
                          tr.status === "success" ? (
                            <Check size={10} />
                          ) : (
                            i + 1
                          )}
                        </span>
                        <strong>{tr.step}</strong>
                        <span>
                          {tr.duration_ms !== null
                            ? `${(tr.duration_ms / 1000).toFixed(1)} s`
                            : "—"}
                        </span>
                      </summary>
                      <div className="trace-detail">
                        <p>{tr.detail}</p>
                        <div className="trace-metrics">
                          {tr.model && <span>模型 {tr.model}</span>}
                          <span>输入 {tr.prompt_tokens} tokens</span>
                          <span>输出 {tr.completion_tokens} tokens</span>
                          <time>{formatDate(tr.created_at)}</time>
                        </div>
                      </div>
                    </details>
                  ))
                ) : (
                  <p className="muted small">
                    任务开始执行后，步骤会显示在这里。
                  </p>
                )}
              </div>
              {task.result && (
                <details className="task-result">
                  <summary>查看执行结果</summary>
                  {typeof (task.result.summary || task.result.report) ===
                  "string" ? (
                    <Markdown>
                      {String(task.result.summary || task.result.report)}
                    </Markdown>
                  ) : (
                    <pre>{JSON.stringify(task.result, null, 2)}</pre>
                  )}
                </details>
              )}
              <p className="small muted task-id">任务 {task.id}</p>
            </section>
          )}
        </div>
      )}
    </>
  );
}
