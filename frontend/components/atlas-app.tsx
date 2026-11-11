"use client";
import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  BookOpen,
  CalendarCheck,
  ChartNoAxesCombined,
  Workflow,
  Menu,
  X,
  Plus,
  Check,
  MessageSquare,
} from "lucide-react";
import { api, ApiError, post } from "@/lib/api";
import type { User } from "@/lib/types";
import { AtlasMark, Loading, ErrorBox } from "./ui";
import { AuthScreen } from "./auth";
import { AccountMenu } from "./account-menu";
import { SettingsDialog, type SettingsTab } from "./settings-dialog";
import { DashboardScreen, CoursesScreen, CreateCourseScreen } from "./home";
import { CourseScreen } from "./course";
import { WorkspaceScreen } from "./workspace";
import { ReviewScreen, AnalyticsScreen } from "./progress";
import { MemoriesScreen, TasksScreen } from "./supporting";
import { TutorScreen } from "./tutor";

const AppContext = createContext<{
  user: User;
  refreshUser: () => Promise<void>;
  notify: (s: string) => void;
} | null>(null);
export function useAtlas() {
  const context = useContext(AppContext);
  if (!context) throw new Error("Missing Atlas context");
  return context;
}
const nav = [
  { href: "/chat", label: "学习对话", icon: MessageSquare },
  { href: "/dashboard", label: "学习工作台", icon: LayoutDashboard },
  { href: "/courses", label: "我的课程", icon: BookOpen },
  { href: "/review", label: "练习与复习", icon: CalendarCheck },
  { href: "/analytics", label: "学习洞察", icon: ChartNoAxesCombined },
];
const secondary = [{ href: "/tasks", label: "Agent 任务", icon: Workflow }];

export default function AtlasApp() {
  const pathname = usePathname(),
    router = useRouter();
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [menu, setMenu] = useState(false),
    [settings, setSettings] = useState<SettingsTab | null>(null),
    [toast, setToast] = useState("");
  const refreshUser = async () => {
    try {
      setUser(await api<User>("/me"));
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setUser(null);
        setSettings(null);
      } else setError(e instanceof Error ? e.message : "无法连接 Atlas 后端");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void refreshUser();
  }, []);
  useEffect(() => {
    setMenu(false);
  }, [pathname]);
  useEffect(() => {
    if (pathname !== "/settings" || !user) return;
    const requested = window.location.hash.slice(1);
    setSettings(
      ["profile", "preferences", "memories", "connections", "privacy"].includes(
        requested,
      )
        ? (requested as SettingsTab)
        : "profile",
    );
  }, [pathname, user?.id, router]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (
      !loading &&
      !error &&
      user &&
      (pathname === "/login" || pathname === "/register")
    )
      router.replace("/");
  }, [user, pathname, loading, error, router]);
  if (loading)
    return (
      <div className="boot">
        <AtlasMark size={46} />
        <Loading label="正在打开 Atlas…" />
      </div>
    );
  if (error)
    return (
      <div className="boot">
        <div className="wordmark">
          <AtlasMark />
          Atlas
        </div>
        <ErrorBox
          message={error}
          retry={() => {
            setLoading(true);
            void refreshUser();
          }}
        />
        <p className="muted">请确认 Atlas 后端正在运行。</p>
      </div>
    );
  if (!user)
    return (
      <AuthScreen
        initialMode={pathname === "/register" ? "register" : "login"}
        onAuthenticated={(u) => {
          setUser(u);
          router.replace("/");
        }}
      />
    );
  const path = pathname.split("/").filter(Boolean);
  const isWorkspace = path[0] === "courses" && path[2] === "learn";
  const isCourseDetail =
    path[0] === "courses" && !!path[1] && path[1] !== "new" && !isWorkspace;
  const isStudyProgress = path[0] === "review" || path[0] === "analytics";
  const isTutor = !path.length || path[0] === "chat";
  let screen;
  if (isTutor) screen = <TutorScreen />;
  else if (path[0] === "dashboard" || path[0] === "settings") screen = <DashboardScreen />;
  else if (path[0] === "courses" && path[1] === "new")
    screen = <CreateCourseScreen />;
  else if (path[0] === "courses" && path[1] && path[2] === "learn" && path[3])
    screen = (
      <WorkspaceScreen courseId={path[1]} nodeId={path[3]} key={path[3]} />
    );
  else if (path[0] === "courses" && path[1])
    screen = <CourseScreen id={path[1]} key={path[1]} />;
  else if (path[0] === "courses") screen = <CoursesScreen />;
  else if (path[0] === "review") screen = <ReviewScreen />;
  else if (path[0] === "analytics") screen = <AnalyticsScreen />;
  else if (path[0] === "memories") screen = <MemoriesScreen />;
  else if (path[0] === "tasks") screen = <TasksScreen />;
  else
    screen = (
      <div className="empty-state">
        <h1>这条路径还没有铺好</h1>
        <Link href="/" className="button">
          回到学习工作台
        </Link>
      </div>
    );
  return (
    <AppContext.Provider value={{ user, refreshUser, notify: setToast }}>
      <div className="app-frame">
        <header className="mobile-header">
          <button
            aria-label="打开导航"
            className="icon-button"
            onClick={() => setMenu(true)}
          >
            <Menu size={21} />
          </button>
          <Link href="/" className="mobile-page-title">
            学习工作台
          </Link>
          <Link
            href="/courses/new"
            aria-label="新建课程"
            className="icon-button"
          >
            <Plus size={20} />
          </Link>
        </header>
        {menu && (
          <button
            className="nav-scrim"
            aria-label="关闭导航"
            onClick={() => setMenu(false)}
          />
        )}
        <aside className={`sidebar ${menu ? "is-open" : ""}`}>
          <Link href="/courses/new" className="nav-item sidebar-create">
            <Plus size={18} />
            新建课程
          </Link>
          <button
            className="mobile-close icon-button"
            aria-label="关闭导航"
            onClick={() => setMenu(false)}
          >
            <X size={20} />
          </button>
          <nav aria-label="主导航">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-item ${(item.href === "/chat" ? isTutor : pathname.startsWith(item.href)) ? "active" : ""}`}
              >
                <item.icon size={18} />
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>
          <nav aria-label="学习管理">
            {secondary.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-item ${pathname.startsWith(item.href) ? "active" : ""}`}
              >
                <item.icon size={18} />
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <AccountMenu
              user={user}
              onOpenSettings={(tab) => {
                setMenu(false);
                setSettings(tab);
              }}
              onLogout={async () => {
                await post("/auth/logout");
                setUser(null);
                router.replace("/login");
              }}
              onError={setToast}
            />
          </div>
        </aside>
        <main
          className={`main-sheet ${isTutor ? "tutor-sheet" : isWorkspace ? "workspace-sheet" : isCourseDetail ? "course-detail-sheet" : isStudyProgress ? "study-sheet" : ""}`}
        >
          <div
            className={`canvas ${isWorkspace ? "canvas-wide" : isCourseDetail ? "canvas-course" : isStudyProgress ? "canvas-study" : ""}`}
          >
            {screen}
          </div>
        </main>
        {settings && (
          <SettingsDialog
            initialTab={settings}
            onClose={() => {
              setSettings(null);
              if (pathname === "/settings") {
                router.replace("/");
                return;
              }
              document
                .querySelector<HTMLButtonElement>(
                  window.matchMedia("(max-width: 650px)").matches
                    ? '.mobile-header [aria-label="打开导航"]'
                    : ".account-trigger",
                )
                ?.focus({ preventScroll: true });
            }}
          />
        )}
        {toast && (
          <div className="toast" role="status">
            <Check size={17} />
            {toast}
            <button
              className="icon-button"
              aria-label="关闭提示"
              onClick={() => setToast("")}
            >
              <X size={14} />
            </button>
          </div>
        )}
      </div>
    </AppContext.Provider>
  );
}
