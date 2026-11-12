"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Activity, Download, RefreshCw } from "lucide-react";
import { api, formatDate } from "@/lib/api";
import { ErrorBox, Loading, Modal } from "./ui";
import "./agent-run-dialog.css";

type RunKind = "agent" | "workflow";
type RunSummary = {
  id: string; kind: RunKind; title: string; status: string;
  course_id: string | null; session_id?: string | null;
  created_at: string; updated_at: string; capability?: string | null; duration_ms?: number | null;
};
type RunSpan = {
  id: string; parent_id?: string | null; kind: "model" | "model_operation" | "tool" | "workflow" | "context";
  name: string; status: string; started_at?: string | null; ended_at?: string | null;
  duration_ms?: number | null; attempt?: number | null; cached?: boolean;
  error?: { code?: string; message?: string; retryable?: boolean } | null;
  usage?: { prompt_tokens?: number | null; completion_tokens?: number | null } | null;
  metadata?: Record<string, unknown> | null;
};
type RunEvent = { id?: string; seq?: number; type: string; created_at?: string | null; payload?: Record<string, unknown> | null };
type RunDetail = {
  run: RunSummary; policy: Record<string, unknown> | null; spans: RunSpan[]; events: RunEvent[];
  usage?: { prompt_tokens?: number | null; completion_tokens?: number | null; model_calls?: number | null; main_model_calls?: number | null; internal_model_calls?: number | null; tool_calls?: number | null; retries?: number | null } | null;
  limitations?: string[];
};
type ToolDefinition = {
  name: string; description: string; group?: string; access?: string; replay_safe?: boolean;
  timeout_seconds?: number | null; modes?: string[]; parameters?: unknown;
};
type ToolCatalog = { profile: string; tools: ToolDefinition[] };

const states: Record<string, string> = {
  queued: "等待开始", pending: "等待开始", running: "运行中", live: "运行中",
  completed: "已完成", succeeded: "已完成", success: "已完成", failed: "失败",
  error: "失败", cancelled: "已停止", canceled: "已停止", waiting_input: "等待回答",
  waiting_confirmation: "等待确认", waiting: "等待操作", skipped: "已跳过", cached: "复用结果",
  interrupted: "执行中断",
};
const spanKinds = { model: "模型", model_operation: "内部模型", tool: "工具", workflow: "流程", context: "上下文" };
const isLive = (status: string) => ["queued", "pending", "running", "live"].includes(status);
const hasNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const number = (value: unknown) => hasNumber(value) ? value.toLocaleString("zh-CN") : "无记录";
const duration = (value: unknown) => hasNumber(value) ? `${(value / 1000).toFixed(2)} 秒` : "无记录";
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "运行记录暂时无法读取。";
const profileName = (detail: RunDetail) => {
  const value = detail.policy?.profile ?? detail.policy?.capability ?? detail.run.capability;
  return typeof value === "string" && ["tutor", "qa", "research", "planner", "solve"].includes(value) ? value : null;
};

export function AgentRunButton({ kind, runId }: { kind: RunKind; runId: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className="text-button agent-run-trigger" onClick={() => setOpen(true)}>
      <Activity size={13} aria-hidden="true" />运行详情
    </button>
    {open && <AgentRunDialog key={`${kind}:${runId}`} kind={kind} runId={runId} onClose={() => setOpen(false)} />}
  </>;
}

function AgentRunDialog({ kind, runId, onClose }: { kind: RunKind; runId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState<"run" | "tools">("run");
  const [catalog, setCatalog] = useState<ToolCatalog | null>(null);
  const [toolsError, setToolsError] = useState("");
  const [toolsRevision, setToolsRevision] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const exportController = useRef<AbortController | null>(null);
  const tabId = useId();
  const path = `/agent/runs/${kind}/${encodeURIComponent(runId)}`;
  const profile = detail ? profileName(detail) : null;

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; exportController.current?.abort(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let keepPolling = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const value = await api<RunDetail>(path, { signal: controller.signal });
        if (!active) return;
        setDetail(value); setError("");
        keepPolling = isLive(value.run.status);
        if (keepPolling) timer = setTimeout(load, 2000);
      } catch (error) {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(error));
          if (keepPolling) timer = setTimeout(load, 2000);
        }
      }
    };
    void load();
    return () => { active = false; controller.abort(); if (timer) clearTimeout(timer); };
  }, [path, revision]);

  useEffect(() => {
    if (tab !== "tools" || !profile) return;
    const controller = new AbortController();
    let active = true;
    setCatalog(null); setToolsError("");
    void api<ToolCatalog>(`/agent/tools?profile=${encodeURIComponent(profile)}`, { signal: controller.signal })
      .then((value) => { if (active) setCatalog(value); })
      .catch((error) => { if (active && !controller.signal.aborted) setToolsError(errorMessage(error)); });
    return () => { active = false; controller.abort(); };
  }, [tab, profile, toolsRevision]);

  async function download() {
    exportController.current?.abort();
    const controller = new AbortController();
    exportController.current = controller;
    setExporting(true); setExportError("");
    try {
      const exported = await api<unknown>(`${path}/export`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `atlas-${kind}-${runId.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (!controller.signal.aborted) setExportError(errorMessage(error));
    } finally {
      if (!controller.signal.aborted) setExporting(false);
    }
  }

  const directTeaching = detail?.events.some((event) => event.type === "answer_route" && event.payload?.route === "direct_teaching");
  return <Modal title="运行详情" className="agent-run-modal" onClose={onClose}>
    <div className="agent-run-content">
      {error && <ErrorBox message={`${error}${detail ? " 下方保留最近一次读取的记录。" : ""}`} retry={() => setRevision((value) => value + 1)} />}
      {!detail ? !error && <Loading /> : <>
        <div className="agent-run-title">
          <div><h3>{detail.run.title || "Atlas 学习任务"}</h3><p>{detail.run.capability === "solve" ? "解题 · 分步推理与受限 Python 计算" : directTeaching ? "直接教学回答 · 使用精简上下文" : kind === "agent" ? "Agent 自主工具循环 · 模型按当前任务选择工具" : "Workflow 固定流程 · 按预先定义的步骤执行"}</p></div>
          <RunStatus status={detail.run.status} />
        </div>
        <div className="agent-run-toolbar">
          <div className="agent-run-tabs" role="tablist" aria-label="运行详情分类" onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "Home" ? "run" : event.key === "End" ? "tools" : tab === "run" ? "tools" : "run";
            setTab(next);
            event.currentTarget.querySelector<HTMLButtonElement>(`[data-tab="${next}"]`)?.focus();
          }}>
            {([ ["run", "执行记录"], ["tools", "工具定义"] ] as const).map(([value, label]) => <button key={value} type="button" role="tab" data-tab={value} id={`${tabId}-${value}`} aria-selected={tab === value} aria-controls={`${tabId}-panel`} tabIndex={tab === value ? 0 : -1} onClick={() => setTab(value)}>{label}</button>)}
          </div>
          <button type="button" className="text-button" onClick={() => setRevision((value) => value + 1)} aria-label="刷新运行记录"><RefreshCw size={14} aria-hidden="true" />刷新</button>
          <button type="button" className="text-button" onClick={() => void download()} disabled={exporting}><Download size={14} aria-hidden="true" />{exporting ? "导出中…" : "导出 JSON"}</button>
        </div>
        {exportError && <ErrorBox message={exportError} retry={() => void download()} />}
        <div id={`${tabId}-panel`} role="tabpanel" aria-labelledby={`${tabId}-${tab}`}>
          {tab === "run" ? <>
            <dl className="agent-run-metrics">
              <Metric label="耗时" value={duration(detail.run.duration_ms)} />
              <Metric label="输入 tokens" value={number(detail.usage?.prompt_tokens)} />
              <Metric label="输出 tokens" value={number(detail.usage?.completion_tokens)} />
              <Metric label="模型调用" value={number(detail.usage?.model_calls)} />
              <Metric label="工具调用" value={number(detail.usage?.tool_calls)} />
              <Metric label="重试" value={number(detail.usage?.retries)} />
            </dl>
            <dl className="agent-run-model-counts"><Metric label="主模型调用" value={number(detail.usage?.main_model_calls)} /><Metric label="内部模型调用" value={number(detail.usage?.internal_model_calls)} /></dl>
            <div className="agent-run-freshness"><span>{isLive(detail.run.status) ? "运行中，每 2 秒更新" : "已保存的执行记录"}</span><span>更新于 {formatDate(detail.run.updated_at)}</span></div>
            <section className="agent-run-section">
              <h3>执行步骤 <span>{detail.spans?.length || 0}</span></h3>
              {detail.spans?.length ? <div className="agent-run-spans"><SpanTree spans={detail.spans} /></div> : <p className="agent-run-empty">这次运行没有详细 span 记录。已有事件会保留在下方；历史运行无法补齐未记录的模型用量与耗时。</p>}
            </section>
            <section className="agent-run-section">
              <h3>事件时间线 <span>{detail.events?.length || 0}</span></h3>
              {detail.events?.length ? <ol className="agent-run-events">{detail.events.map((event, index) => <li key={event.id || `${event.seq ?? index}:${event.type}`}>
                <span className="agent-run-event-dot" aria-hidden="true" />
                <div><strong>{eventLabel(event.type)}</strong><p>{eventSummary(event)}</p></div>
                <time>{event.created_at ? formatDate(event.created_at) : hasNumber(event.seq) ? `#${event.seq}` : "时间无记录"}</time>
              </li>)}</ol> : <p className="agent-run-empty">尚无可展示的执行事件。</p>}
            </section>
            <details className="agent-run-policy"><summary>执行策略与权限</summary><Policy detail={detail} /></details>
            {!!detail.limitations?.length && <div className="agent-run-limitations">{detail.limitations.map((item, index) => <p key={index}>{item}</p>)}</div>}
          </> : <section className="agent-run-section agent-run-catalog">
            <h3>{profile ? `${profile} 工具定义` : "工具定义"}</h3><p className="agent-run-hint">工具是否可执行，还受本轮模式、权限与确认要求约束。</p>
            {!profile ? <p className="agent-run-empty">{kind === "workflow" ? "固定流程未使用 Agent 工具 profile。可在 Tutor 运行中查看对应能力的工具定义。" : "这次运行没有记录能力 profile，无法确定当时的工具范围。"}</p> : toolsError ? <ErrorBox message={toolsError} retry={() => setToolsRevision((value) => value + 1)} /> : !catalog ? <Loading /> : !catalog.tools.length ? <p className="agent-run-empty">这个能力范围没有公开工具定义。</p> : catalog.tools.map((tool) => <details className="agent-run-tool" key={tool.name}>
              <summary><strong>{tool.name}</strong><span>{accessLabel(tool.access)}</span></summary>
              <p>{tool.description}</p>
              <dl className="agent-run-key-values">
                <Metric label="分组" value={tool.group || "无记录"} />
                <Metric label="模式" value={tool.modes?.join("、") || "无记录"} />
                <Metric label="可安全重放" value={typeof tool.replay_safe === "boolean" ? tool.replay_safe ? "是" : "否" : "无记录"} />
                <Metric label="超时" value={hasNumber(tool.timeout_seconds) ? `${tool.timeout_seconds} 秒` : "无记录"} />
              </dl>
              <details className="agent-run-json"><summary>参数 schema · 开发详情</summary><pre>{tool.parameters ? JSON.stringify(tool.parameters, null, 2) : "无记录"}</pre></details>
            </details>)}
          </section>}
        </div>
        <p className="agent-run-footnote">仅展示执行事件和公开调用信息。模型私有思维、密钥及私有 checkpoint 不在此展示或导出。</p>
      </>}
    </div>
  </Modal>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd className={value === "无记录" ? "agent-run-missing" : undefined}>{value}</dd></div>;
}

function RunStatus({ status }: { status: string }) {
  return <span className={`agent-run-status${["failed", "error"].includes(status) ? " is-failed" : ["completed", "succeeded", "success"].includes(status) ? " is-completed" : ""}`} role="status">{states[status] || status}</span>;
}

function SpanTree({ spans }: { spans: RunSpan[] }) {
  const ids = new Set(spans.map((span) => span.id));
  function branch(span: RunSpan, ancestors: Set<string>) {
    if (ancestors.has(span.id)) return null;
    const visited = new Set([...ancestors, span.id]);
    const children = spans.filter((child) => child.parent_id === span.id);
    return <SpanRow key={span.id} span={span}>{children.length ? children.map((child) => branch(child, visited)) : undefined}</SpanRow>;
  }
  const roots = spans.filter((span) => !span.parent_id || !ids.has(span.parent_id));
  return <>{(roots.length ? roots : spans).map((span) => branch(span, new Set()))}</>;
}

function SpanRow({ span, children }: { span: RunSpan; children?: React.ReactNode }) {
  // Only explicit public metadata is shown; raw provider payloads and checkpoints stay private.
  const metadata = Object.entries(span.metadata || {}).filter(([key, value]) => ["model", "provider", "protocol", "tool", "round", "call_id", "finish_reason", "step", "access", "estimated_tokens", "message_count", "tool_count", "estimation", "capability", "operation", "role", "step_id", "plan_version", "execution_id", "scope"].includes(key) && ["string", "number", "boolean"].includes(typeof value));
  return <details className="agent-run-span">
    <summary><span className="agent-run-span-kind">{span.metadata?.scope === "internal" ? "内部模型" : spanKinds[span.kind] || "步骤"}</span><strong>{span.name}</strong><RunStatus status={span.status} /><span className="agent-run-duration">{duration(span.duration_ms)}</span></summary>
    <div className="agent-run-span-body">
      <dl className="agent-run-key-values">
        <Metric label="开始" value={span.started_at ? formatDate(span.started_at) : "无记录"} />
        <Metric label="结束" value={span.ended_at ? formatDate(span.ended_at) : "无记录"} />
        {["model", "model_operation"].includes(span.kind) && <><Metric label="输入 tokens" value={number(span.usage?.prompt_tokens)} /><Metric label="输出 tokens" value={number(span.usage?.completion_tokens)} /></>}
        {span.kind === "tool" && <Metric label="计时范围" value="包含内部调用" />}
        <Metric label="尝试次数" value={number(span.attempt)} />
        {span.kind === "tool" && <Metric label="回执缓存" value={typeof span.cached === "boolean" ? span.cached ? "已复用" : "未复用" : "无记录"} />}
      </dl>
      {span.error && <div className="agent-run-span-error"><strong>{span.error.code || "执行失败"}</strong>{span.error.message && <p>{span.error.message}</p>}{typeof span.error.retryable === "boolean" && <span>{span.error.retryable ? "此错误允许按策略重试" : "此错误不自动重试"}</span>}</div>}
      {metadata.length > 0 && <details className="agent-run-json"><summary>调用标识 · 开发详情</summary><dl className="agent-run-key-values">{metadata.map(([key, value]) => <Metric key={key} label={key} value={String(value)} />)}</dl></details>}
      {children && <div className="agent-run-children">{children}</div>}
    </div>
  </details>;
}

function Policy({ detail }: { detail: RunDetail }) {
  if (detail.run.kind === "workflow" && !detail.policy) return <p className="agent-run-hint">这次运行使用固定步骤 Workflow，没有 Agent Loop 的能力 profile 与循环预算。</p>;
  const policy = detail.policy || {};
  const budgets = typeof policy.budgets === "object" && policy.budgets ? policy.budgets as Record<string, unknown> : policy;
  const tools = policy.allowed_tools ?? policy.allowed_names ?? policy.tools;
  const permissions = policy.permissions ?? policy.allowed_access;
  return <>
    <dl className="agent-run-key-values">
      <Metric label="能力" value={typeof (policy.capability ?? detail.run.capability) === "string" ? String(policy.capability ?? detail.run.capability) : "无记录"} />
      <Metric label="工具 profile" value={typeof (policy.profile ?? detail.run.capability) === "string" ? String(policy.profile ?? detail.run.capability) : "无记录"} />
      {([ ["max_rounds", "最大循环轮数"], ["max_tool_calls", "工具调用预算"], ["max_model_retries", "模型重试上限"], ["timeout_seconds", "运行时限（秒）"] ] as const).map(([key, label]) => <Metric key={key} label={label} value={number(budgets[key])} />)}
      <Metric label="权限范围" value={Array.isArray(permissions) && permissions.every((item) => typeof item === "string") ? permissions.join("、") || "无" : typeof permissions === "string" ? permissions : "无记录"} />
    </dl>
    {Array.isArray(tools) && tools.every((item) => typeof item === "string") && <div className="agent-run-permissions"><span>允许调用的工具</span><p>{tools.join("、") || "无"}</p></div>}
  </>;
}

function accessLabel(access?: string) {
  return ({ read: "读取", state: "学习状态", write: "写入", proposal: "变更提案", execute: "受限执行", execution: "受限执行" } as Record<string, string>)[access || ""] || access || "权限无记录";
}

function eventLabel(type: string) {
  if (type === "answer_route") return "选择回答方式";
  const learningLabels: Record<string, string> = { retrieval_result: "资料检索", memory_recalled: "读取学习记忆", memory_saved: "保存学习记忆", memory_forgotten: "忘记学习记忆", memory_profile: "整理学习画像" };
  if (learningLabels[type]) return learningLabels[type];
  return ({ model_operation_start: "内部模型调用开始", model_operation: "内部模型调用", solve_plan: "更新解题计划", solve_execution: "计算执行结果", solve_complete: "解题结果", practice_validation: "练习核验", model_start: "模型调用开始", model_end: "模型调用结束", model_error: "模型调用失败", tool_start: "工具开始", tool_result: "工具返回", tool_retry: "工具重试", tool_cached: "复用工具回执", context_budget: "上下文预算", status: "状态更新", content: "生成回答", content_reset: "更新回答", question: "准备练习", assessment: "作答评估", confirmation: "等待确认", input_required: "等待回答", user_response: "收到补充回答", citations: "补充来源", question_repaired: "题目修复完成", done: "本轮结束", error: "执行失败", cancelled: "已停止", workflow: "流程步骤" } as Record<string, string>)[type] || "执行事件";
}

function eventSummary(event: RunEvent) {
  const payload = event.payload || {};
  if (event.type === "answer_route") return payload.route === "direct_teaching" ? "直接教学回答" : "Agent 工具循环";
  const parts: string[] = [];
  if (["retrieval_result", "memory_recalled", "memory_saved", "memory_forgotten", "memory_profile"].includes(event.type)) {
    // Summarize an explicit public allowlist, never raw queries, facts, quotations or tool results.
    if (event.type === "retrieval_result") {
      const engineNames: Record<string, string> = { atlas: "Atlas", llamaindex: "LlamaIndex", pageindex: "PageIndex", lightrag: "LightRAG" };
      if (Array.isArray(payload.engines_used)) {
        const engines = payload.engines_used.flatMap((engine) => (
          typeof engine === "string" && Object.hasOwn(engineNames, engine) ? [engineNames[engine]] : []
        ));
        if (engines.length) parts.push(engines.join(" + "));
      }
      const routeLabels: Record<string, string> = {
        page_location: "查找原文页码",
        cross_document: "查找跨资料关系",
        model_supplement: "模型选择补充检索",
      };
      if (typeof payload.route_reason === "string" && Object.hasOwn(routeLabels, payload.route_reason)) {
        parts.push(routeLabels[payload.route_reason]);
      }
      const strategy = ({ original: "原查询检索", lexical: "关键词检索", hybrid: "融合检索", fusion: "融合检索", fallback: "原查询回退" } as Record<string, string>)[typeof payload.strategy === "string" ? payload.strategy : ""];
      if (strategy) parts.push(strategy);
      for (const [key, label] of [["query_count", "查询"], ["candidate_count", "候选片段"], ["source_count", "来源"]]) {
        if (hasNumber(payload[key]) && payload[key] >= 0) parts.push(`${label} ${number(Math.trunc(payload[key]))}`);
      }
      if (payload.rewritten === true) parts.push("已扩展查询");
      if (payload.reranked === true) parts.push("已核对候选排序");
      const warnings: Record<string, string> = {
        embedding_unverified: "旧向量待重建",
        embedding_model_changed: "索引模型已变化",
        embedding_dimension_mismatch: "向量维度不匹配",
        embedding_unavailable: "向量服务不可用",
        hybrid_unavailable: "融合检索不可用",
        knowledge_engine_unavailable: "检索引擎不可用，已回退",
        knowledge_index_stale: "资料索引待更新，已回退",
        knowledge_source_not_indexed: "部分资料使用 Atlas 检索",
        knowledge_index_queue_unavailable: "后台索引暂不可用",
        knowledge_pages_not_ready: "页级索引尚未就绪",
        knowledge_graph_not_ready: "图谱尚不可用",
        knowledge_graph_queued: "图谱已排队，先使用通用检索",
        knowledge_no_specialized_evidence: "已用通用检索补充证据",
      };
      if (Array.isArray(payload.warnings)) {
        for (const warning of payload.warnings) {
          if (typeof warning === "string" && warnings[warning]) parts.push(warnings[warning]);
        }
      }
    }
    if (hasNumber(payload.memory_count) && payload.memory_count >= 0) parts.push(`${number(Math.trunc(payload.memory_count))} 条记忆`);
    const profile = ({ empty: "尚无学习画像", pending: "画像整理中", ready: "画像有效", stale: "画像已过期", failed: "画像整理未完成" } as Record<string, string>)[typeof payload.profile_status === "string" ? payload.profile_status : ""];
    if (profile) parts.push(profile);
    return parts.join(" · ") || ({ retrieval_result: "检索记录已保存", memory_recalled: "有效记忆已按当前学习范围读取", memory_saved: "学习记忆操作已记录", memory_forgotten: "记忆已停止用于后续讲解", memory_profile: "画像整理操作已记录" } as Record<string, string>)[event.type];
  }
  if (["tool_start", "tool_result", "tool_retry", "tool_cached"].includes(event.type)) {
    if (typeof payload.tool === "string") parts.push(payload.tool);
    else if (typeof payload.name === "string") parts.push(payload.name);
    if (hasNumber(payload.attempt)) parts.push(`尝试 ${payload.attempt} 次`);
  }
  if (event.type.startsWith("model_") && typeof payload.model === "string") parts.push(payload.model);
  if (event.type === "model_operation" && typeof payload.name === "string") parts.push(payload.name);
  if (typeof payload.capability === "string") parts.push(payload.capability);
  if (typeof payload.status === "string") parts.push(states[payload.status] || payload.status);
  if (hasNumber(payload.duration_ms)) parts.push(duration(payload.duration_ms));
  if (typeof payload.code === "string") parts.push(payload.code);
  if (event.type === "context_budget") {
    if (hasNumber(payload.estimated_tokens)) parts.push(`估算 ${number(payload.estimated_tokens)} tokens`);
    if (hasNumber(payload.max_tokens)) parts.push(`上限 ${number(payload.max_tokens)} tokens`);
  }
  return parts.join(" · ") || ({ content: "回答内容已更新", content_reset: "回答内容已更新", confirmation: "等待你在原对话中确认变更", input_required: "等待你在原对话中继续作答", question: "练习题已交给原对话", assessment: "作答结果已交给原对话", tool_result: "工具结果已保存", done: "执行记录已保存" } as Record<string, string>)[event.type] || "执行事件已记录";
}
