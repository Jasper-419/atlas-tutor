"use client";
import { useState, type FormEvent } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { post } from "@/lib/api";
import type { User } from "@/lib/types";
import { AtlasMark, ErrorBox } from "./ui";

export function AuthScreen({
  initialMode,
  onAuthenticated,
}: {
  initialMode: "login" | "register";
  onAuthenticated: (u: User) => void;
}) {
  const [mode, setMode] = useState(initialMode),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      onAuthenticated(
        await post<User>(`/auth/${mode}`, Object.fromEntries(form)),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page auth-minimal">
      <header className="auth-minimal-header">
        <div className="wordmark">
          <AtlasMark size={32} />
          <span>Atlas</span>
        </div>
      </header>
      <section className="auth-form-area">
        <div className="auth-form-wrap">
          <div className="auth-heading">
            <h1>{mode === "login" ? "欢迎来到 Atlas" : "开启你的学习旅程"}</h1>
            <p>
              {mode === "login"
                ? "从上一次的理解，继续向前。"
                : "把想学的事，变成走得通的路。"}
            </p>
          </div>
          <form onSubmit={submit} className="form-stack">
            {mode === "register" && (
              <label>
                怎么称呼你
                <input
                  name="full_name"
                  placeholder="你的名字"
                  autoComplete="name"
                  required
                  maxLength={80}
                />
              </label>
            )}
            <label>
              邮箱地址
              <input
                name="email"
                type="email"
                placeholder="请输入你的邮箱"
                autoComplete="email"
                required
              />
            </label>
            <label>
              密码
              <input
                name="password"
                type="password"
                placeholder={
                  mode === "register" ? "至少 8 个字符" : "输入你的密码"
                }
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                minLength={mode === "register" ? 8 : 1}
                maxLength={128}
                required
              />
            </label>
            {error && <ErrorBox message={error} />}
            <button className="button primary auth-submit" disabled={busy}>
              {busy ? (
                <Loader2 size={17} className="spin" />
              ) : mode === "login" ? (
                "继续"
              ) : (
                "创建账号"
              )}
              {!busy && <ArrowRight size={16} />}
            </button>
          </form>
          <p className="auth-switch">
            {mode === "login" ? "还没有账号？" : "已经有账号？"}
            <button
              className="text-button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError("");
              }}
            >
              {mode === "login" ? "创建一个账号" : "直接登录"}
            </button>
          </p>
          <p className="auth-private">
            你的课程、对话与学习记忆，保存在独立的个人空间。
          </p>
        </div>
      </section>
      <footer className="auth-minimal-footer">
        <span>Atlas AI Learning OS</span>
        <span>让每一次好奇，都通向理解。</span>
      </footer>
    </main>
  );
}
