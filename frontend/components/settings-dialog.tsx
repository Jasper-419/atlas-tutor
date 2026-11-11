"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  Brain,
  Check,
  Plug,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
} from "lucide-react";
import { api, useResource } from "@/lib/api";
import type { SystemStatus, User } from "@/lib/types";
import { useAtlas } from "./atlas-app";
import { MemoriesScreen } from "./supporting";
import { ErrorBox, Loading, Modal } from "./ui";
import { ModelConnectionsPanel } from "./llm-connections";

const sections = [
  { id: "profile", label: "个人资料", icon: UserRound },
  { id: "preferences", label: "学习偏好", icon: SlidersHorizontal },
  { id: "memories", label: "学习记忆", icon: Brain },
  { id: "connections", label: "AI 连接", icon: Plug },
  { id: "privacy", label: "数据与隐私", icon: ShieldCheck },
] as const;

export type SettingsTab = (typeof sections)[number]["id"];

export function SettingsDialog({
  initialTab,
  onClose,
}: {
  initialTab: SettingsTab;
  onClose: () => void;
}) {
  const { user, refreshUser } = useAtlas();
  const [tab, setTab] = useState(initialTab);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [compact, setCompact] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const media = window.matchMedia("(max-width: 650px)");
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener("change", update);
    return () => {
      document.body.style.overflow = previous;
      media.removeEventListener("change", update);
    };
  }, []);

  function selectTab(next: SettingsTab) {
    setTab(next);
    setError("");
    setSaved(false);
    panel.current?.scrollTo(0, 0);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await api<User>("/me", {
        method: "PATCH",
        body: JSON.stringify(
          tab === "profile"
            ? {
                full_name: String(form.get("full_name")).trim(),
              }
            : {
                preferences: {
                  ...user.preferences,
                  explanation_style: form.get("explanation_style"),
                  daily_minutes: Number(form.get("daily_minutes")),
                },
              },
        ),
      });
      await refreshUser();
      setSaved(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : "保存失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="设置" className="settings-modal" onClose={onClose}>
      <div className="settings-layout">
        <div
          className="settings-tabs"
          role="tablist"
          aria-label="设置分类"
          aria-orientation={compact ? "horizontal" : "vertical"}
          onKeyDown={(event) => {
            const nextKey = compact ? "ArrowRight" : "ArrowDown";
            const previousKey = compact ? "ArrowLeft" : "ArrowUp";
            if (![nextKey, previousKey, "Home", "End"].includes(event.key))
              return;
            event.preventDefault();
            const current = sections.findIndex((section) => section.id === tab);
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? sections.length - 1
                  : (current +
                      (event.key === nextKey ? 1 : -1) +
                      sections.length) %
                    sections.length;
            selectTab(sections[next].id);
            event.currentTarget
              .querySelectorAll<HTMLButtonElement>("[role=tab]")
              [next]?.focus();
          }}
        >
          {sections.map(({ id: value, label, icon: Icon }) => (
            <button
              key={value}
              id={`${id}-${value}`}
              type="button"
              role="tab"
              aria-selected={tab === value}
              aria-controls={`${id}-panel`}
              tabIndex={tab === value ? 0 : -1}
              disabled={busy}
              onClick={() => selectTab(value)}
            >
              <Icon size={17} aria-hidden="true" />
              {label}
            </button>
          ))}
        </div>
        <div
          ref={panel}
          id={`${id}-panel`}
          className="settings-content"
          role="tabpanel"
          aria-labelledby={`${id}-${tab}`}
          tabIndex={0}
        >
          <h2 className="settings-content-title">
            {sections.find((section) => section.id === tab)?.label}
          </h2>
          {tab === "profile" || tab === "preferences" ? (
            <form
              key={tab}
              className="form-stack settings-form"
              onSubmit={save}
              onChange={() => setSaved(false)}
            >
              {tab === "profile" ? (
                <>
                  <label>
                    称呼
                    <input
                      name="full_name"
                      defaultValue={user.full_name || ""}
                      required
                      maxLength={80}
                      pattern=".*\S.*"
                    />
                  </label>
                  <label>
                    邮箱
                    <input value={user.email} readOnly aria-readonly="true" />
                  </label>
                </>
              ) : (
                <>
                  <label>
                    讲解方式
                    <select
                      name="explanation_style"
                      defaultValue={String(
                        user.preferences?.explanation_style || "example",
                      )}
                    >
                      <option value="example">先看例子，再讲原理</option>
                      <option value="theory">先建立框架，再看例子</option>
                      <option value="socratic">通过提问逐步理解</option>
                      <option value="concise">简洁，突出关键点</option>
                    </select>
                  </label>
                  <label>
                    每日学习时间
                    <select
                      name="daily_minutes"
                      defaultValue={String(
                        user.preferences?.daily_minutes || 30,
                      )}
                    >
                      <option value="15">15 分钟</option>
                      <option value="30">30 分钟</option>
                      <option value="60">60 分钟</option>
                      <option value="90">90 分钟</option>
                    </select>
                  </label>
                </>
              )}
              {error && <ErrorBox message={error} />}
              <div className="settings-form-actions">
                {saved && (
                  <span className="settings-saved" role="status">
                    <Check size={15} aria-hidden="true" />
                    已保存
                  </span>
                )}
                <button className="button primary" disabled={busy}>
                  {busy ? "保存中…" : "保存"}
                </button>
              </div>
            </form>
          ) : tab === "memories" ? (
            <MemoriesScreen embedded />
          ) : tab === "connections" ? (
            <ConnectionsPanel />
          ) : (
            <PrivacyPanel onMemories={() => selectTab("memories")} />
          )}
        </div>
      </div>
    </Modal>
  );
}

function ConnectionsPanel() {
  const {
    data: status,
    error,
    reload,
  } = useResource<SystemStatus>("/system/status");
  return (
    <>
      <ModelConnectionsPanel />
      <details className="model-other-services">
        <summary>资料与研究服务</summary>
        {error ? (
          <ErrorBox message={error} retry={reload} />
        ) : !status ? (
          <Loading />
        ) : (
          [
            {
              title: "资料检索",
              description: status.embedding_configured
                ? "语义与关键词混合检索"
                : "关键词检索",
              available: true,
              state: "可用",
            },
            {
              title: "联网资料研究",
              description: status.search_configured
                ? "搜索与公开文档研究"
                : "公开文档 URL 研究",
              available: true,
              state: "可用",
            },
          ].map((item) => (
            <div className="settings-data-row" key={item.title}>
              <div>
                <h3>{item.title}</h3>
                <p>{item.description}</p>
              </div>
              <span
                className={`status ${item.available ? "status-succeeded" : "status-failed"}`}
              >
                <i />
                {item.state}
              </span>
            </div>
          ))
        )}
        <p className="settings-hint">资料检索与联网研究由服务端配置。</p>
      </details>
    </>
  );
}

function PrivacyPanel({ onMemories }: { onMemories: () => void }) {
  const { refreshUser } = useAtlas();
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <>
      <div className="settings-data-row">
        <div>
          <h3>导出学习数据</h3>
          <p>下载课程、对话、练习和记忆。</p>
        </div>
        <a href="/api/me/export" className="button" download>
          导出
        </a>
      </div>
      <div className="settings-data-row">
        <div>
          <h3>学习记忆</h3>
          <p>查看、修正或删除已保存的记忆。</p>
        </div>
        <button className="button" onClick={onMemories}>
          管理
        </button>
      </div>
      <div className="settings-data-row">
        <div>
          <h3>删除账号</h3>
          <p>永久删除账号和全部私人学习数据。</p>
        </div>
        <button
          className="button danger"
          disabled={deleting}
          onClick={() => setDeleting(true)}
        >
          删除
        </button>
      </div>
      {deleting && (
        <form
          className="form-stack settings-delete-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setBusy(true);
            setError("");
            try {
              await api("/me", {
                method: "DELETE",
                body: JSON.stringify({ password: form.get("password") }),
              });
              await refreshUser();
            } catch (error) {
              setError(
                error instanceof Error ? error.message : "删除失败，请重试。",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <p className="settings-hint">此操作无法撤销。输入当前密码以确认。</p>
          <label>
            当前密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              autoFocus
            />
          </label>
          {error && <ErrorBox message={error} />}
          <div className="settings-form-actions">
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => {
                setDeleting(false);
                setError("");
              }}
            >
              取消
            </button>
            <button className="button danger-button" disabled={busy}>
              {busy ? "删除中…" : "永久删除账号"}
            </button>
          </div>
        </form>
      )}
    </>
  );
}
