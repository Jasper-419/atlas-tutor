"use client";

import { useId, useState, type FormEvent } from "react";
import { Check, ChevronLeft, Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { api, post, useResource } from "@/lib/api";
import type { LLMConnection, LLMConnections, LLMProtocol } from "@/lib/types";
import { ErrorBox, Loading } from "./ui";

const root = "/me/llm-connections";
const protocols: { value: LLMProtocol; label: string }[] = [
  { value: "openai-completions", label: "OpenAI Chat Completions" },
  { value: "openai-responses", label: "OpenAI Responses" },
  { value: "anthropic-messages", label: "Anthropic Messages" },
];
const presets = {
  deepseek: {
    name: "DeepSeek",
    base_url: "https://api.deepseek.com/v1",
    protocol: "openai-completions" as LLMProtocol,
    models: "deepseek-flash",
  },
  openai: {
    name: "OpenAI",
    base_url: "https://api.openai.com/v1",
    protocol: "openai-responses" as LLMProtocol,
    models: "",
  },
  anthropic: {
    name: "Anthropic",
    base_url: "https://api.anthropic.com/v1",
    protocol: "anthropic-messages" as LLMProtocol,
    models: "",
  },
  custom: {
    name: "",
    base_url: "",
    protocol: "openai-completions" as LLMProtocol,
    models: "",
  },
};
type Preset = keyof typeof presets;

export function ModelConnectionsPanel() {
  const {
    data,
    setData,
    error: loadError,
    reload,
  } = useResource<LLMConnections>(root);
  const [editor, setEditor] = useState<LLMConnection | "new" | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  if (loadError) return <ErrorBox message={loadError} retry={reload} />;
  if (!data) return <Loading />;

  async function changeActive(connectionId: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(root + "/active", {
        method: "PUT",
        body: JSON.stringify({ connection_id: connectionId || null }),
      });
      setData((previous) =>
        previous
          ? { ...previous, active_connection_id: connectionId || null }
          : previous,
      );
      setNotice("已切换，下次 AI 请求生效。");
    } catch (error) {
      setError(error instanceof Error ? error.message : "切换失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function remove(connection: LLMConnection) {
    setBusy(true);
    setError("");
    try {
      await api(root + "/" + connection.id, { method: "DELETE" });
      setData((previous) =>
        previous
          ? {
              ...previous,
              connections: previous.connections.filter(
                (item) => item.id !== connection.id,
              ),
              active_connection_id:
                previous.active_connection_id === connection.id
                  ? null
                  : previous.active_connection_id,
            }
          : previous,
      );
      setDeleting(null);
      setNotice("连接已删除。");
    } catch (error) {
      setError(error instanceof Error ? error.message : "删除失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  if (editor)
    return (
      <ConnectionEditor
        key={editor === "new" ? "new" : editor.id}
        connection={editor === "new" ? null : editor}
        onCancel={() => setEditor(null)}
        onSaved={() => {
          setEditor(null);
          setNotice("连接已保存，下次 AI 请求生效。");
          reload();
        }}
      />
    );

  return (
    <div className="model-connections">
      <p className="model-intro">
        为课程规划、AI 导师与练习添加自己的模型 API。
      </p>
      <label className="model-active-field">
        当前使用
        <select
          aria-label="当前使用的 AI 连接"
          value={data.active_connection_id || ""}
          disabled={busy}
          onChange={(event) => void changeActive(event.target.value)}
        >
          <option value="">
            {data.server_configured
              ? `服务端默认 · ${data.server_model}`
              : "服务端默认（尚未配置）"}
          </option>
          {data.connections.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.model}
            </option>
          ))}
        </select>
      </label>
      <div className="model-list-heading">
        <h3>我的连接</h3>
        <button
          className="button"
          disabled={busy}
          onClick={() => {
            setEditor("new");
            setError("");
            setNotice("");
          }}
        >
          <Plus size={15} />
          添加连接
        </button>
      </div>
      {data.connections.length === 0 ? (
        <p className="model-empty">
          还没有添加连接。支持 DeepSeek、OpenAI、Anthropic 和自定义 API。
        </p>
      ) : (
        data.connections.map((connection) => (
          <div className="model-connection-row" key={connection.id}>
            <div className="model-connection-info">
              <h4>
                {connection.name}
                {data.active_connection_id === connection.id && (
                  <span className="model-current">
                    <Check size={13} />
                    使用中
                  </span>
                )}
              </h4>
              <p>{connection.model}</p>
              <small>
                {connection.has_api_key ? "API Key 已保存" : "无 API Key"} ·{" "}
                {
                  protocols.find((item) => item.value === connection.protocol)
                    ?.label
                }
              </small>
            </div>
            <div className="model-row-actions">
              <button
                className="button"
                disabled={busy}
                aria-label={`编辑 ${connection.name}`}
                onClick={() => {
                  setEditor(connection);
                  setError("");
                  setNotice("");
                }}
              >
                编辑
              </button>
              <button
                className="icon-button"
                disabled={busy}
                aria-label={`删除 ${connection.name}`}
                onClick={() => {
                  setDeleting(connection.id);
                  setNotice("");
                }}
              >
                <Trash2 size={16} />
              </button>
            </div>
            {deleting === connection.id && (
              <div className="model-delete-confirm">
                <p>
                  删除此连接？
                  {data.active_connection_id === connection.id
                    ? "删除后将使用服务端默认配置。"
                    : ""}
                </p>
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => setDeleting(null)}
                >
                  取消
                </button>
                <button
                  className="button danger"
                  disabled={busy}
                  onClick={() => void remove(connection)}
                >
                  {busy ? "删除中…" : "确认删除"}
                </button>
              </div>
            )}
          </div>
        ))
      )}
      {error && <ErrorBox message={error} />}
      {notice && (
        <p className="model-notice" role="status">
          <Check size={14} />
          {notice}
        </p>
      )}
      <p className="settings-hint model-security-hint">
        密钥加密保存在服务端，仅用于你的模型请求，保存后不会回传。
      </p>
    </div>
  );
}

function ConnectionEditor({
  connection,
  onCancel,
  onSaved,
}: {
  connection: LLMConnection | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const id = useId();
  const [preset, setPreset] = useState<Preset>(
    connection ? "custom" : "deepseek",
  );
  const [draft, setDraft] = useState({
    name: connection?.name || presets.deepseek.name,
    base_url: connection?.base_url || presets.deepseek.base_url,
    protocol: connection?.protocol || presets.deepseek.protocol,
    api_key: "",
    models: connection?.models.join("\n") || presets.deepseek.models,
    model: connection?.model || "",
  });
  const [clearKey, setClearKey] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | "discover" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [available, setAvailable] = useState<string[] | null>(null);
  const [search, setSearch] = useState("");
  const models = Array.from(
    new Set(
      draft.models
        .split(/[\n,，]/)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  );
  const selected = models.includes(draft.model) ? draft.model : models[0] || "";
  const changedEndpoint = Boolean(
    connection?.has_api_key &&
      (connection.base_url !== draft.base_url.trim().replace(/\/+$/, "") ||
        connection.protocol !== draft.protocol),
  );

  function update<K extends keyof typeof draft>(
    key: K,
    value: (typeof draft)[K],
  ) {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setNotice("");
    setError("");
    if (key === "base_url" || key === "protocol") setAvailable(null);
    if (key === "api_key") setRevealed(false);
  }

  function payload() {
    return {
      ...draft,
      model: selected,
      models,
      api_key: clearKey ? "" : draft.api_key,
      connection_id: clearKey ? undefined : connection?.id,
    };
  }

  async function probe(kind: "test" | "discover") {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      if (kind === "discover") {
        const result = await post<{ models: string[] }>(
          root + "/discover",
          payload(),
        );
        setAvailable(result.models);
        setSearch("");
        setNotice(`找到 ${result.models.length} 个模型，勾选后保存。`);
      } else {
        const result = await post<{ message: string }>(
          root + "/test",
          payload(),
        );
        setNotice(result.message);
      }
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "请求失败，请检查配置。",
      );
    } finally {
      setBusy(null);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError("");
    setNotice("");
    try {
      await api(root + (connection ? "/" + connection.id : ""), {
        method: connection ? "PUT" : "POST",
        body: JSON.stringify({
          ...payload(),
          connection_id: connection?.id,
          clear_api_key: clearKey,
        }),
      });
      setDraft((previous) => ({ ...previous, api_key: "" }));
      onSaved();
    } catch (error) {
      setError(error instanceof Error ? error.message : "保存失败，请重试。");
    } finally {
      setBusy(null);
    }
  }

  const needsKey = changedEndpoint && !clearKey && !draft.api_key.trim();
  return (
    <div className="model-editor">
      <button
        type="button"
        className="model-back"
        disabled={Boolean(busy)}
        onClick={onCancel}
      >
        <ChevronLeft size={16} />
        {connection ? "编辑连接" : "添加连接"}
      </button>
      <form className="form-stack model-connection-form" onSubmit={save}>
        <fieldset disabled={Boolean(busy)}>
          {!connection && (
            <label>
              服务商
              <select
                value={preset}
                onChange={(event) => {
                  const next = event.target.value as Preset;
                  setPreset(next);
                  setDraft({ ...presets[next], api_key: "", model: "" });
                  setAvailable(null);
                  setError("");
                  setNotice("");
                  setRevealed(false);
                }}
              >
                <option value="deepseek">DeepSeek</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="custom">自定义 API</option>
              </select>
            </label>
          )}
          <label>
            连接名称
            <input
              value={draft.name}
              onChange={(event) => update("name", event.target.value)}
              placeholder="例如：我的模型服务"
              required
              maxLength={100}
              pattern=".*\S.*"
            />
          </label>
          <label>
            API 地址
            <input
              type="url"
              value={draft.base_url}
              onChange={(event) => update("base_url", event.target.value)}
              placeholder="https://your-provider.com/v1"
              required
              maxLength={2000}
              spellCheck={false}
              aria-describedby={`${id}-url-hint`}
            />
          </label>
          <p className="settings-hint model-field-hint" id={`${id}-url-hint`}>
            填写基础地址，通常以 /v1 结尾，不含 /chat/completions 等操作路径。
          </p>
          <label>
            API 协议
            <select
              value={draft.protocol}
              onChange={(event) =>
                update("protocol", event.target.value as LLMProtocol)
              }
            >
              {protocols.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="model-key-field">
            <label htmlFor={`${id}-key`}>API Key</label>
            <div className="model-key-input">
              <input
                id={`${id}-key`}
                value={draft.api_key}
                type={revealed ? "text" : "password"}
                autoComplete="new-password"
                spellCheck={false}
                maxLength={4096}
                disabled={clearKey}
                onChange={(event) => update("api_key", event.target.value)}
                placeholder={
                  connection?.has_api_key && !clearKey
                    ? "留空以保留已保存的密钥"
                    : "填写密钥；无鉴权的本地服务可留空"
                }
              />
              {draft.api_key && (
                <button
                  type="button"
                  className="icon-button"
                  aria-label={revealed ? "隐藏密钥" : "显示密钥"}
                  aria-pressed={revealed}
                  onClick={() => setRevealed((value) => !value)}
                >
                  {revealed ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              )}
            </div>
            {connection?.has_api_key && (
              <label className="model-checkbox">
                <input
                  type="checkbox"
                  checked={clearKey}
                  onChange={(event) => {
                    setClearKey(event.target.checked);
                    update("api_key", "");
                  }}
                />
                清除已保存的密钥
              </label>
            )}
            {needsKey && (
              <p className="settings-hint model-field-hint">
                API 地址或协议已更改，请重新填写密钥。
              </p>
            )}
          </div>
          <div className="model-catalog-heading">
            <label htmlFor={`${id}-models`}>模型 ID</label>
            <button
              type="button"
              className="button"
              disabled={!draft.base_url.trim() || needsKey}
              onClick={() => void probe("discover")}
            >
              {busy === "discover" ? "获取中…" : "获取模型列表"}
            </button>
          </div>
          <textarea
            id={`${id}-models`}
            value={draft.models}
            onChange={(event) => update("models", event.target.value)}
            rows={2}
            required
            maxLength={40000}
            spellCheck={false}
            placeholder="每行一个模型 ID，也可以用逗号分隔"
          />
          <p className="settings-hint model-field-hint">
            可手动填写服务商提供的模型 ID，获取列表失败也能保存。
          </p>
          {available && (
            <div className="model-discovery">
              <input
                type="search"
                aria-label="搜索可用模型"
                placeholder="搜索可用模型"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <div className="model-discovery-options">
                {available
                  .filter((model) =>
                    model.toLowerCase().includes(search.toLowerCase()),
                  )
                  .map((model) => (
                    <label className="model-checkbox" key={model}>
                      <input
                        type="checkbox"
                        checked={models.includes(model)}
                        onChange={(event) =>
                          update(
                            "models",
                            (event.target.checked
                              ? [...models, model]
                              : models.filter((value) => value !== model)
                            ).join("\n"),
                          )
                        }
                      />
                      <span>{model}</span>
                    </label>
                  ))}
                {!available.some((model) =>
                  model.toLowerCase().includes(search.toLowerCase()),
                ) && <p className="settings-hint">没有匹配的模型。</p>}
              </div>
            </div>
          )}
          <label>
            默认模型
            <select
              value={selected}
              required
              onChange={(event) => update("model", event.target.value)}
            >
              <option value="" disabled>
                请先填写或选择模型
              </option>
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        {error && <ErrorBox message={error} />}
        {notice && (
          <p className="model-notice" role="status">
            <Check size={14} />
            {notice}
          </p>
        )}
        <div className="model-editor-actions">
          <button
            className="button"
            type="button"
            disabled={
              Boolean(busy) || !selected || !draft.base_url.trim() || needsKey
            }
            onClick={() => void probe("test")}
          >
            {busy === "test" ? "测试中…" : "测试连接"}
          </button>
          <span />
          <button
            className="button"
            type="button"
            disabled={Boolean(busy)}
            onClick={onCancel}
          >
            取消
          </button>
          <button
            className="button primary"
            disabled={Boolean(busy) || models.length === 0 || needsKey}
          >
            {busy === "save" ? "保存中…" : "保存连接"}
          </button>
        </div>
        <p className="settings-hint">
          测试会发送一条简短请求，可能产生少量 API 用量。
        </p>
      </form>
    </div>
  );
}
