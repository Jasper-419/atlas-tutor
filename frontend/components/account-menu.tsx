"use client";

import { useEffect, useId, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import {
  Brain,
  LogOut,
  MoreHorizontal,
  Settings,
  SlidersHorizontal,
  UserRound,
} from "lucide-react";
import type { User } from "@/lib/types";
import type { SettingsTab } from "./settings-dialog";

const destinations = [
  { tab: "profile", label: "个人资料", icon: UserRound },
  { tab: "preferences", label: "学习偏好", icon: SlidersHorizontal },
  { tab: "memories", label: "学习记忆", icon: Brain },
  { tab: "privacy", label: "设置与隐私", icon: Settings },
] as const;

export function AccountMenu({
  user,
  onOpenSettings,
  onLogout,
  onError,
}: {
  user: User;
  onOpenSettings: (tab: SettingsTab) => void;
  onLogout: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const id = useId();
  const pathname = usePathname();
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const initialFocus = useRef<"first" | "last">("first");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const name = user.full_name || "学习者";
  const initial = (user.full_name || user.email).charAt(0).toUpperCase();

  function position() {
    if (!trigger.current || !popup.current) return;
    const rect = trigger.current.getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 24);
    Object.assign(popup.current.style, {
      width: `${width}px`,
      left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`,
      bottom: `${window.innerHeight - rect.top + 8}px`,
      maxHeight: `${Math.max(120, rect.top - 20)}px`,
    });
  }

  function close(restoreFocus = false) {
    popup.current?.hidePopover();
    if (restoreFocus) trigger.current?.focus();
  }

  useEffect(() => {
    popup.current?.hidePopover();
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener("resize", position);
    return () => window.removeEventListener("resize", position);
  }, [open]);

  return (
    <div className="account-menu">
      <button
        ref={trigger}
        type="button"
        className="account-trigger"
        aria-label="打开用户菜单"
        aria-haspopup="menu"
        aria-controls={id}
        aria-expanded={open}
        popoverTarget={id}
        onClick={() => {
          initialFocus.current = "first";
          position();
        }}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
          event.preventDefault();
          initialFocus.current = event.key === "ArrowUp" ? "last" : "first";
          position();
          popup.current?.showPopover();
        }}
      >
        <span className="avatar" aria-hidden="true">
          {initial}
        </span>
        <strong>{name}</strong>
        <MoreHorizontal size={18} aria-hidden="true" />
      </button>
      <div
        id={id}
        ref={popup}
        popover="auto"
        className="account-popover"
        role="menu"
        aria-label="用户菜单"
        onToggle={(event) => {
          const element = event.currentTarget;
          const visible = element.matches(":popover-open");
          setOpen(visible);
          if (visible) {
            position();
            requestAnimationFrame(() => {
              if (!element.matches(":popover-open")) return;
              const items = element.querySelectorAll<HTMLElement>(
                "[role=menuitem]:not(:disabled)",
              );
              items[
                initialFocus.current === "last" ? items.length - 1 : 0
              ]?.focus();
            });
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            close(true);
          } else if (event.key === "Tab") {
            close(true);
          } else if (
            ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)
          ) {
            event.preventDefault();
            const items = Array.from(
              event.currentTarget.querySelectorAll<HTMLElement>(
                "[role=menuitem]:not(:disabled)",
              ),
            );
            const current = items.indexOf(
              document.activeElement as HTMLElement,
            );
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? items.length - 1
                  : (current +
                      (event.key === "ArrowDown" ? 1 : -1) +
                      items.length) %
                    items.length;
            items[next]?.focus();
          }
        }}
      >
        <div className="account-popover-header" role="presentation">
          <span className="avatar" aria-hidden="true">
            {initial}
          </span>
          <span>
            <strong>{name}</strong>
            <small>{user.email}</small>
          </span>
        </div>
        <div
          className="account-menu-group"
          role="group"
          aria-label="账号与偏好"
        >
          {destinations.map(({ tab, label, icon: Icon }) => (
            <button
              key={tab}
              type="button"
              role="menuitem"
              tabIndex={-1}
              className="account-menu-item"
              onClick={() => {
                close(true);
                onOpenSettings(tab);
              }}
            >
              <Icon size={19} aria-hidden="true" />
              {label}
            </button>
          ))}
        </div>
        <div className="account-menu-group" role="group" aria-label="登录管理">
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            className="account-menu-item"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onLogout();
              } catch (error) {
                onError(
                  error instanceof Error
                    ? error.message
                    : "退出登录失败，请重试。",
                );
                setBusy(false);
              }
            }}
          >
            <LogOut size={19} aria-hidden="true" />
            {busy ? "正在退出…" : "退出登录"}
          </button>
        </div>
      </div>
    </div>
  );
}
