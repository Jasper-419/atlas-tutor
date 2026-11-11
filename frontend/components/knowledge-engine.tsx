"use client";

import { useState } from "react";
import { post, useResource } from "@/lib/api";
import type { AgentTask } from "@/lib/types";
import { Modal } from "./ui";

type Engine = "auto" | "atlas" | "llamaindex" | "pageindex" | "lightrag";
type IndexTask = AgentTask & { engine: Engine };
type KnowledgeState = {
  engine: Engine;
  stale: boolean;
  embedding_configured: boolean;
  searchable: boolean;
  indexing: boolean;
  engines: { id: Engine; label: string; unavailable: string | null }[];
  task: IndexTask | null;
};

const descriptions: Record<Engine, string> = {
  auto: "Atlas 会根据资料和问题自动选择检索方式。",
  atlas: "课程资料的原生检索",
  llamaindex: "向量与 BM25 混合检索",
  pageindex: "按 PDF 章节和页码检索",
  lightrag: "跨资料检索概念与关系",
};

export function KnowledgeEngine({ courseId }: { courseId: string }) {
  const path = `/courses/${courseId}/knowledge`;
  const [choice, setChoice] = useState<Engine | null>(null);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const { data, setData, error: loadError, reload } = useResource<KnowledgeState>(path, 2500);
  if (!data) return loadError ? <p className="knowledge-engine muted" role="alert">{loadError}</p> : null;
  const { engine, engines, task, stale, searchable, indexing } = data;
  const failed = task?.status === "failed";
  const running = task?.status === "queued" || task?.status === "running";
  const selected = choice ?? (running || failed ? task?.engine : null) ?? engine;
  const option = engines.find((item) => item.id === selected);
  const activeLabel = engines.find((item) => item.id === engine)?.label ?? "Atlas";
  const hint = selected === "llamaindex" && !data.embedding_configured
    ? "未配置 Embedding，LlamaIndex 使用 BM25。"
    : descriptions[selected];
  const status = error || (running
    ? `${option?.label} 构建中 · ${task.progress}% · 正在使用 ${activeLabel}`
    : failed
      ? task.error || "索引构建未完成，可重新构建。"
      : stale ? "资料或模型已更新，请重建索引。" : option?.unavailable || hint);
  const materialStatus = searchable
    ? indexing ? "资料可检索 · 正在补建索引" : "资料可检索"
    : indexing ? "正在准备索引" : "上传资料后即可检索";

  return (
    <>
      <div className="knowledge-engine">
        <span className="muted" role="status">{materialStatus}</span>
        <button type="button" className="text-button" onClick={() => setOpen(true)}>
          高级检索设置
        </button>
      </div>
      {open && (
        <Modal title="高级检索设置" onClose={() => { setOpen(false); setChoice(null); setError(""); }}>
          <form className="form-stack" onSubmit={async (event) => {
            event.preventDefault();
            setSubmitting(true);
            setError("");
            try {
              const next = await post<IndexTask>(path, { engine: selected });
              setData((previous) => previous && { ...previous, task: next });
              setChoice(null);
              reload();
            } catch (cause) {
              setError((cause as Error).message);
            } finally {
              setSubmitting(false);
            }
          }}>
            <label>
              检索方式
              <select value={selected} disabled={running || submitting}
                onChange={(event) => { setChoice(event.target.value as Engine); setError(""); }}>
                {engines.map(({ id, label, unavailable }) => (
                  <option key={id} value={id} disabled={Boolean(unavailable)}>
                    {label}{unavailable ? ` · ${unavailable.replace(/。$/, "")}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className={error || failed ? "knowledge-error" : "muted"} role="status">{status}</span>
            {(selected !== engine || !["atlas", "auto"].includes(engine) || failed) && (
              <div className="row-actions">
                <button className="button" disabled={running || submitting || Boolean(option?.unavailable)}>
                  {selected !== engine ? "应用" : "重建索引"}
                </button>
              </div>
            )}
          </form>
        </Modal>
      )}
    </>
  );
}
