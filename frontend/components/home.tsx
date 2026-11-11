"use client";
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Plus,
  Clock,
  ArrowUpRight,
  Loader2,
  Search,
  Route,
  CalendarCheck,
  Network,
} from "lucide-react";
import { useResource, post, formatDate } from "@/lib/api";
import type { Course, DashboardData, Template } from "@/lib/types";
import { useAtlas } from "./atlas-app";
import {
  PageTitle,
  Loading,
  ErrorBox,
  Empty,
  CourseRow,
  Breadcrumb,
} from "./ui";

export function DashboardScreen() {
  const { user } = useAtlas(),
    { data, error, loading, reload } = useResource<DashboardData>("/dashboard");
  const router = useRouter(),
    [goal, setGoal] = useState("");
  const date = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
  if (loading) return <Loading />;
  if (error || !data)
    return <ErrorBox message={error || "没有获取到学习数据"} retry={reload} />;
  const next = data.courses.find(
    (c) => c.next_node_id && c.status === "active",
  );
  return (
    <>
      <header className="dashboard-heading">
        <div>
          <p className="today-date">{date}</p>
          <h1>{user.full_name || "学习者"}，今天想学点什么？</h1>
          <p className="muted">
            {data.stats.courses
              ? `你已经连接了 ${data.stats.mastered_nodes} 个知识节点。沿着好奇，继续向前。`
              : "从一个想学会的问题开始，找到属于你的学习路径。"}
          </p>
        </div>
      </header>
      <form
        className="goal-composer"
        onSubmit={(e) => {
          e.preventDefault();
          router.push(`/courses/new?goal=${encodeURIComponent(goal)}`);
        }}
      >
        <textarea
          name="learning_goal"
          aria-label="新的学习目标"
          rows={2}
          placeholder="我想学会…"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          maxLength={2000}
          required
          minLength={3}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div>
          <button
            className="goal-send"
            aria-label="规划这个学习目标"
            disabled={goal.trim().length < 3}
          >
            <ArrowRight size={19} />
          </button>
        </div>
      </form>
      <div className="goal-suggestions">
        {["系统掌握 LangGraph", "搭建一个 RAG 应用", "巩固 Python 基础"].map(
          (g) => (
            <button key={g} onClick={() => setGoal(g)}>
              {g}
              <ArrowUpRight size={12} />
            </button>
          ),
        )}
      </div>
      <div className="stats-strip">
        {[
          ["课程总数", data.stats.courses, ""],
          [
            "已掌握知识",
            data.stats.mastered_nodes,
            `共 ${data.stats.total_nodes} 个知识节点`,
          ],
          ["待复习", data.stats.due_reviews, ""],
          ["累计学习", data.stats.learning_minutes, "分钟 · 按学习活动估算"],
        ].map(([label, value, caption]) => (
          <div className="stat" key={String(label)}>
            <span>{label}</span>
            <strong>{value}</strong>
            {caption && <small>{caption}</small>}
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <section className="panel courses-panel">
          <div className="section-heading">
            <h2>
              你的学习路径 <span className="count">{data.courses.length}</span>
            </h2>
            <Link href="/courses" className="text-link">
              全部课程 <ArrowUpRight size={14} />
            </Link>
          </div>
          {data.courses.length ? (
            <div className="course-list">
              {data.courses.slice(0, 4).map((c) => (
                <CourseRow key={c.id} course={c} />
              ))}
            </div>
          ) : (
            <div className="start-learning">
              <h3>从一个想学会的问题开始。</h3>
              <p>
                告诉 Atlas 你的目标、已有基础和每天可投入的时间，
                <br className="desktop-only" />
                把一个大问题，拆成一步步能走的知识路径。
              </p>
              <Link href="/courses/new" className="button">
                创建第一门课程 <ArrowRight size={16} />
              </Link>
            </div>
          )}
        </section>
        <section className="panel today-panel">
          <div className="section-heading">
            <h2>今天的一小步</h2>
            <Clock size={16} />
          </div>
          {next ? (
            <>
              <span className="small muted">接着上次的进度</span>
              <h3>{next.title}</h3>
              <p className="muted">
                每日 {next.minutes_per_day} 分钟，按自己的节奏前进。
              </p>
              <Link
                href={`/courses/${next.id}/learn/${next.next_node_id}`}
                className="button"
              >
                继续学习 <ArrowRight size={16} />
              </Link>
            </>
          ) : (
            <>
              <div className="today-symbol">
                <Route size={35} strokeWidth={1.1} />
              </div>
              <h3>先给好奇心一个方向。</h3>
              <p className="muted">创建自己的目标，或从一门精选入门课开始。</p>
              <Link href="/courses/new" className="text-link">
                找到你的起点 <ArrowRight size={15} />
              </Link>
            </>
          )}
        </section>
        <section className="panel">
          <div className="section-heading">
            <h2>需要再次相遇的知识</h2>
            <Link href="/review" className="text-link">
              前往复习 <ArrowUpRight size={14} />
            </Link>
          </div>
          {data.reviews.length ? (
            data.reviews.slice(0, 4).map((r) => (
              <Link
                className="simple-row"
                href={`/courses/${r.course_id}/learn/${r.node_id}`}
                key={r.id}
              >
                <CalendarCheck size={16} />
                <div>
                  <strong>{r.node_title}</strong>
                  <small>{r.course_title}</small>
                </div>
                <ArrowRight size={16} />
              </Link>
            ))
          ) : (
            <div className="quiet-empty">
              <CalendarCheck size={20} strokeWidth={1.3} />
              <p>今天没有到期的复习。</p>
              <span>完成练习后，Atlas 会为知识安排下一次相遇。</span>
            </div>
          )}
        </section>
        <section className="panel">
          <div className="section-heading">
            <h2>最近的足迹</h2>
            <span className="small muted">学习记录</span>
          </div>
          {data.activity.length ? (
            <div className="activity-list">
              {data.activity.slice(0, 4).map((a) => (
                <div className="activity-row" key={a.id}>
                  <span className="activity-dot" />
                  <div>
                    <strong>{a.title}</strong>
                    <p>{a.detail}</p>
                  </div>
                  <time>{formatDate(a.created_at, true)}</time>
                </div>
              ))}
            </div>
          ) : (
            <div className="quiet-empty">
              <Network size={20} strokeWidth={1.3} />
              <p>你的知识地图，正等待第一笔。</p>
              <span>课程、练习和新的理解，都会在这里留下足迹。</span>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

export function CoursesScreen() {
  const { data, error, loading, reload } = useResource<Course[]>("/courses"),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all");
  const courses = (data || []).filter(
    (c) =>
      (filter === "all" || c.status === filter) &&
      `${c.title} ${c.goal}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="course-catalog">
      <PageTitle title="我的课程" description="管理课程与学习进度。">
        <Link href="/courses/new" className="button primary">
          <Plus size={17} />
          新建学习目标
        </Link>
      </PageTitle>
      <div className="filter-row">
        <div className="tabs">
          {[
            ["all", "全部课程"],
            ["active", "学习中"],
            ["completed", "已完成"],
          ].map(([v, l]) => (
            <button
              key={v}
              className={filter === v ? "active" : ""}
              onClick={() => setFilter(v)}
            >
              {l}
            </button>
          ))}
        </div>
        <label className="search-field">
          <Search size={16} />
          <input
            placeholder="搜索课程"
            aria-label="搜索课程"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} retry={reload} />
      ) : courses.length ? (
        <section className="panel course-catalog-list">
          {courses.map((c) => (
            <CourseRow key={c.id} course={c} />
          ))}
        </section>
      ) : (
        <Empty
          title={
            query ? "还没有找到这门课程" : "给一个好奇的问题，留一条学习路径"
          }
          description={
            query
              ? "试试其他关键词。"
              : "从你的目标出发，生成适合已有基础和可用时间的课程。"
          }
        >
          <Link href="/courses/new" className="button primary">
            创建课程 <ArrowRight size={16} />
          </Link>
        </Empty>
      )}
    </div>
  );
}

export function CreateCourseScreen() {
  const router = useRouter(),
    { notify } = useAtlas(),
    { data: templates } = useResource<Template[]>("/templates");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [enrolling, setEnrolling] = useState(""),
    [initialGoal, setInitialGoal] = useState("");
  useEffect(() => {
    setInitialGoal(
      new URLSearchParams(window.location.search).get("goal") || "",
    );
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      const c = await post<Course>("/courses", {
        goal: f.get("goal"),
        background: f.get("background"),
        minutes_per_day: Number(f.get("minutes_per_day")),
        deadline: f.get("deadline") || null,
        level: f.get("level"),
      });
      notify("目标已保存，Atlas 正在规划你的知识路径。");
      router.push(`/courses/${c.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <>
      <Breadcrumb
        items={[
          { label: "我的课程", href: "/courses" },
          { label: "新的学习目标" },
        ]}
      />
      <PageTitle
        title="你想学会什么？"
        description="从真正想解决的问题开始，Atlas 会帮你找到合适的路。"
      />
      <div className="create-grid">
        <section className="panel form-panel">
          <form className="form-stack" onSubmit={submit}>
            <label>
              我的学习目标
              <textarea
                name="goal"
                rows={4}
                value={initialGoal}
                onChange={(e) => setInitialGoal(e.target.value)}
                required
                minLength={6}
                maxLength={2000}
                placeholder="例如：我想用一个月学会 LangGraph，能独立构建带记忆和工具调用的 AI Agent。"
              />
              <small>越具体的目标，越容易拆成可行动的知识节点。</small>
            </label>
            <label>
              已经知道些什么？
              <textarea
                name="background"
                rows={3}
                maxLength={2000}
                placeholder="例如：熟悉 Python 和 HTTP API，了解基础大模型调用，没有用过 LangGraph。"
              />
            </label>
            <div className="form-two-col">
              <label>
                当前起点
                <select name="level" defaultValue="beginner">
                  <option value="beginner">刚刚开始</option>
                  <option value="intermediate">已有一些基础</option>
                  <option value="advanced">进阶与系统巩固</option>
                </select>
              </label>
              <label>
                每天可以投入
                <select name="minutes_per_day" defaultValue="30">
                  <option value="15">15 分钟</option>
                  <option value="30">30 分钟</option>
                  <option value="60">60 分钟</option>
                  <option value="90">90 分钟</option>
                  <option value="120">120 分钟</option>
                </select>
              </label>
            </div>
            <label>
              期望完成日期 <span className="muted">（可选）</span>
              <input
                type="date"
                name="deadline"
                min={new Date().toLocaleDateString("en-CA")}
              />
            </label>
            {error && <ErrorBox message={error} />}
            <div className="form-footer">
              <span className="small muted">课程会保存到你的个人空间。</span>
              <button className="button primary" disabled={busy}>
                {busy ? (
                  <>
                    <Loader2 className="spin" size={16} />
                    正在创建…
                  </>
                ) : (
                  <>
                    生成学习路径 <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </form>
        </section>
        <aside className="create-aside">
          <div className="aside-intro">
            <AtlasPath />
            <h2>从目标，到真正掌握。</h2>
            <p>
              课程会围绕你的基础组织先修知识，让每一步都有来处，也有下一步。
            </p>
            <ol>
              <li>
                <span>01</span>把目标拆成知识节点
              </li>
              <li>
                <span>02</span>连接前置依赖和学习顺序
              </li>
              <li>
                <span>03</span>通过练习调整学习节奏
              </li>
            </ol>
          </div>
        </aside>
      </div>
      <section className="templates-section">
        <div className="section-heading">
          <div>
            <h2>或者，从一段精选路径开始</h2>
            <p className="muted small">
              人工编写的入门课程，可直接开始；AI 导师与拓展功能仍使用真实模型。
            </p>
          </div>
        </div>
        <div className="template-grid">
          {templates?.map((t, i) => (
            <article className="template-card" key={t.id}>
              <span className="template-index">0{i + 1}</span>
              <h3>{t.title}</h3>
              <p>{t.description}</p>
              <div className="template-topics">
                {t.topics.slice(0, 3).join(" / ")}
              </div>
              <button
                className="text-button"
                disabled={!!enrolling}
                onClick={async () => {
                  setEnrolling(t.id);
                  try {
                    const c = await post<Course>(`/templates/${t.id}/enroll`);
                    router.push(`/courses/${c.id}`);
                  } catch (e) {
                    notify((e as Error).message);
                    setEnrolling("");
                  }
                }}
              >
                {enrolling === t.id ? (
                  <Loader2 size={15} className="spin" />
                ) : (
                  <>
                    开始这段路径 <ArrowUpRight size={15} />
                  </>
                )}
              </button>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
function AtlasPath() {
  return (
    <div className="aside-path" aria-hidden="true">
      <svg viewBox="0 0 240 110">
        <path
          d="M10 85Q65 85 75 50T140 45 215 15"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        {[
          [10, 85],
          [75, 50],
          [140, 45],
          [215, 15],
        ].map(([x, y], i) => (
          <circle
            key={i}
            cx={x}
            cy={y}
            r="5"
            fill={i < 2 ? "currentColor" : "#f1f3ef"}
            stroke="currentColor"
            strokeWidth="1.5"
          />
        ))}
      </svg>
    </div>
  );
}
