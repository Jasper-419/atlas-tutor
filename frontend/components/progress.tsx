"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  RefreshCw,
  Search,
} from "lucide-react";
import { post, useResource, formatDate } from "@/lib/api";
import type {
  AnalyticsData,
  AnalyticsNode,
  Attempt,
  Course,
  Review,
} from "@/lib/types";
import { useAtlas } from "./atlas-app";
import {
  Empty,
  ErrorBox,
  Loading,
  Markdown,
  Modal,
  PageTitle,
  Progress,
} from "./ui";

export function ReviewScreen() {
  const { notify } = useAtlas();
  const reviewsResource = useResource<Review[]>("/review/due");
  const attemptsResource = useResource<Attempt[]>("/attempts?incorrect=true");
  const coursesResource = useResource<Course[]>("/courses");
  const [tab, setTab] = useState("review");
  const [courseId, setCourseId] = useState("all");
  const [query, setQuery] = useState("");
  const [rating, setRating] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const search = query.trim().toLocaleLowerCase();
  const reviews = (reviewsResource.data || []).filter(
    (item) =>
      (courseId === "all" || item.course_id === courseId) &&
      `${item.node_title} ${item.course_title}`
        .toLocaleLowerCase()
        .includes(search),
  );
  const attempts = (attemptsResource.data || []).filter(
    (item) =>
      (courseId === "all" || item.course_id === courseId) &&
      `${item.prompt || ""} ${item.node_title || ""} ${item.course_title || ""}`
        .toLocaleLowerCase()
        .includes(search),
  );
  const resource = tab === "review" ? reviewsResource : attemptsResource;
  const hasFilter = courseId !== "all" || !!search;
  const clearFilters = () => {
    setCourseId("all");
    setQuery("");
  };

  return (
    <div className="study-screen review-screen">
      <div className="study-header">
        <PageTitle
          title="练习与复习"
          description="处理到期复习，回看错题与反馈。"
        >
          <button
            className="icon-button"
            aria-label="刷新复习数据"
            title="刷新"
            onClick={() => {
              reviewsResource.reload();
              attemptsResource.reload();
              coursesResource.reload();
            }}
          >
            <RefreshCw size={17} />
          </button>
          <Link href="/courses" className="button">
            我的课程
            <ArrowRight size={15} />
          </Link>
        </PageTitle>
      </div>
      <div className="review-toolbar">
        <div className="review-tabs" role="group" aria-label="复习分类">
          <button
            type="button"
            data-mode="review"
            aria-pressed={tab === "review"}
            onClick={() => setTab("review")}
          >
            到期复习
            {reviewsResource.data && (
              <span className="count">{reviews.length}</span>
            )}
          </button>
          <button
            type="button"
            data-mode="mistakes"
            aria-pressed={tab === "mistakes"}
            onClick={() => setTab("mistakes")}
          >
            错题与薄弱点
            {attemptsResource.data && (
              <span className="count">{attempts.length}</span>
            )}
          </button>
        </div>
        <div className="review-filters">
          <select
            aria-label="按课程筛选"
            value={courseId}
            onChange={(event) => setCourseId(event.target.value)}
          >
            <option value="all">全部课程</option>
            {coursesResource.data?.map((course) => (
              <option value={course.id} key={course.id}>
                {course.title}
              </option>
            ))}
          </select>
          <label className="search-field">
            <Search size={15} />
            <input
              type="search"
              aria-label="搜索复习内容"
              placeholder="搜索知识点或题目"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>
      </div>
      <div
        className="study-content review-content"
        role="region"
        aria-label={tab === "review" ? "到期复习列表" : "错题列表"}
        tabIndex={0}
      >
        {resource.loading ? (
          <Loading label="正在读取学习记录…" />
        ) : resource.error ? (
          <ErrorBox message={resource.error} retry={resource.reload} />
        ) : tab === "review" && reviews.length ? (
          <>
            <div className="review-table-head" aria-hidden="true">
              <span>知识点</span>
              <span>掌握度</span>
              <span>复习操作</span>
            </div>
            <div className="review-list">
              {reviews.map((review) => (
                <article className="review-item" key={review.id}>
                  <div className="review-item-info">
                    <span className="review-course" title={review.course_title}>
                      {review.course_title}
                    </span>
                    <h2>{review.node_title}</h2>
                    <p>
                      应于 {formatDate(review.due_at, true)} 复习 · 复习间隔{" "}
                      {review.interval_days} 天
                    </p>
                  </div>
                  <div className="review-item-mastery">
                    <span>{Math.round(review.mastery)}%</span>
                    <Progress value={review.mastery} />
                  </div>
                  <div className="review-item-actions">
                    <Link
                      href={`/courses/${review.course_id}/learn/${review.node_id}`}
                      className="button"
                    >
                      回顾知识
                      <ArrowRight size={14} />
                    </Link>
                    <button
                      className="text-button"
                      onClick={() => {
                        setRating(review);
                        setActionError("");
                      }}
                    >
                      <Check size={15} />
                      记录复习
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </>
        ) : tab === "mistakes" && attempts.length ? (
          <div className="mistakes-list">
            {attempts.map((attempt) => (
              <article className="mistake-item" key={attempt.id}>
                <details>
                  <summary>
                    <span className="mistake-summary">
                      <span className="mistake-course">
                        {attempt.course_title} · {attempt.node_title}
                      </span>
                      <span className="mistake-preview">
                        {(attempt.prompt || "练习回顾").replace(/^#+\s*/, "")}
                      </span>
                      <span className="mistake-disclosure">
                        查看作答与反馈
                        <ChevronRight size={14} />
                      </span>
                    </span>
                    <span className="mistake-score">
                      {Math.round(attempt.score)}
                      <small>/ 100</small>
                    </span>
                  </summary>
                  <div className="answer-history">
                    <strong>题目</strong>
                    <Markdown>{attempt.prompt || "练习回顾"}</Markdown>
                    <strong>我的回答</strong>
                    <Markdown>{attempt.answer}</Markdown>
                    <strong>反馈</strong>
                    <Markdown>{attempt.feedback}</Markdown>
                    {attempt.correct_answer && (
                      <>
                        <strong>参考答案</strong>
                        <Markdown>{attempt.correct_answer}</Markdown>
                      </>
                    )}
                  </div>
                </details>
                <div className="mistake-footer">
                  <time>{formatDate(attempt.created_at)}</time>
                  {attempt.course_id && (
                    <Link
                      href={`/courses/${attempt.course_id}/learn/${attempt.node_id}`}
                      className="text-link"
                    >
                      回到知识点
                      <ArrowRight size={14} />
                    </Link>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title={
              hasFilter
                ? "没有符合筛选的记录"
                : tab === "review"
                  ? "暂无到期复习"
                  : "暂无错题记录"
            }
            description={
              hasFilter
                ? "调整课程或关键词，查看其他记录。"
                : tab === "review"
                  ? "完成课程练习后，Atlas 会根据掌握情况安排复习。"
                  : "需要巩固的作答与反馈会保存在这里。"
            }
          >
            {hasFilter ? (
              <button className="button" onClick={clearFilters}>
                清除筛选
              </button>
            ) : (
              <Link href="/courses" className="button">
                查看课程
                <ArrowRight size={15} />
              </Link>
            )}
          </Empty>
        )}
      </div>
      {rating && (
        <Modal title="记录复习" onClose={() => setRating(null)}>
          <p className="muted">
            {rating.node_title} · 选择本次掌握情况，更新下次复习时间。
          </p>
          <div className="rating-options">
            {[
              [1, "还很模糊", "需要重新理解"],
              [2, "有些吃力", "想起了一部分"],
              [3, "基本记得", "需要一点提示"],
              [4, "比较清晰", "可以独立解释"],
              [5, "很有把握", "能举例并应用"],
            ].map(([value, title, description]) => (
              <button
                className="rating-option"
                key={Number(value)}
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setActionError("");
                  try {
                    await post(`/review/${rating.id}/complete`, {
                      rating: Number(value),
                    });
                    setRating(null);
                    reviewsResource.reload();
                    notify("复习已记录，下次复习时间已更新。");
                  } catch (error) {
                    setActionError((error as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <span>{value}</span>
                <strong>{title}</strong>
                <small>{description}</small>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
          {actionError && <ErrorBox message={actionError} />}
        </Modal>
      )}
    </div>
  );
}

const nodeHref = (node: AnalyticsNode) =>
  node.status === "locked"
    ? `/courses/${node.course_id}`
    : `/courses/${node.course_id}/learn/${node.node_id}`;

export function AnalyticsScreen() {
  const { data, error, loading, reload } =
    useResource<AnalyticsData>("/analytics");
  const attempts = data?.stats.attempts || 0;
  const description = data?.stats.due_reviews
    ? `${data.stats.due_reviews} 项复习已到期，建议优先处理。`
    : data?.weak_nodes.length
      ? `${data.weak_nodes.length} 个知识点值得继续巩固。`
      : "查看学习节奏与知识掌握情况。";
  return (
    <div className="study-screen insights-screen">
      <div className="study-header">
        <PageTitle title="学习洞察" description={description}>
          <button
            className="icon-button"
            aria-label="刷新学习洞察"
            title="刷新"
            onClick={reload}
          >
            <RefreshCw size={17} />
          </button>
          <Link
            href="/review"
            className={`button ${data?.stats.due_reviews ? "primary" : ""}`}
          >
            练习与复习
            <ArrowRight size={15} />
          </Link>
        </PageTitle>
      </div>
      {loading ? (
        <Loading label="正在读取学习数据…" />
      ) : error || !data ? (
        <ErrorBox message={error || "学习数据暂不可用"} retry={reload} />
      ) : (
        <>
          <div className="insights-stats">
            {[
              ["累计练习", attempts, "次作答"],
              [
                "平均得分",
                attempts ? Math.round(data.stats.average_score || 0) : "—",
                attempts ? "满分 100 分" : "暂无作答",
              ],
              [
                "已掌握知识",
                data.stats.mastered_nodes,
                `共 ${data.stats.total_nodes} 个节点`,
              ],
              ["学习用时", data.stats.learning_minutes, "分钟 · 活动估算"],
            ].map(([label, value, hint]) => (
              <div className="insights-stat" key={String(label)}>
                <span>{label}</span>
                <strong>{value}</strong>
                <small>{hint}</small>
              </div>
            ))}
          </div>
          <div className="insights-body">
            <div
              className="insights-main"
              role="region"
              aria-label="学习节奏与知识掌握"
              tabIndex={0}
            >
              <section className="insights-section activity-panel">
                <div className="insights-section-heading">
                  <h2>学习节奏</h2>
                  <span>近 14 天 · 每日练习次数</span>
                </div>
                <ActivityChart points={data.daily_activity} />
              </section>
              <section className="insights-section mastery-panel">
                <div className="insights-section-heading">
                  <h2>知识掌握</h2>
                  <span>全部课程 · {data.mastery.length} 个节点</span>
                </div>
                {data.mastery.length ? (
                  <div className="mastery-table">
                    <div className="mastery-table-head" aria-hidden="true">
                      <span>知识点 / 课程</span>
                      <span>掌握度</span>
                    </div>
                    {data.mastery.map((node) => (
                      <Link
                        href={nodeHref(node)}
                        className="mastery-table-row"
                        key={node.node_id}
                      >
                        <span className="insight-node-link">
                          <strong>{node.title}</strong>
                          <small>{node.course_title}</small>
                        </span>
                        <div className="mastery-table-value">
                          <Progress value={node.mastery} />
                          <span>{Math.round(node.mastery)}%</span>
                          <ArrowUpRight size={14} aria-hidden="true" />
                        </div>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <p className="study-empty-note">
                    还没有知识节点。
                    <Link href="/courses">
                      查看课程
                      <ArrowRight size={14} />
                    </Link>
                  </p>
                )}
              </section>
            </div>
            <aside className="insights-aside" aria-label="学习建议与 AI 用量">
              <section className="insights-section weak-panel">
                <div className="insights-section-heading">
                  <h2>待巩固知识</h2>
                  <span>{data.weak_nodes.length} 项</span>
                </div>
                {data.weak_nodes.length ? (
                  <div
                    className="weak-node-list"
                    tabIndex={0}
                    aria-label="待巩固知识列表"
                  >
                    {data.weak_nodes.map((node) => (
                      <Link
                        href={nodeHref(node)}
                        className="weak-node-row"
                        key={node.node_id}
                      >
                        <div>
                          <strong>{node.title}</strong>
                          <small>{node.course_title}</small>
                        </div>
                        <span>{Math.round(node.mastery)}%</span>
                        <ArrowUpRight size={14} aria-hidden="true" />
                      </Link>
                    ))}
                  </div>
                ) : (
                  <p className="study-empty-note">
                    暂无待巩固节点。练习后会提供具体建议。
                  </p>
                )}
              </section>
              <section className="insights-section usage-panel">
                <div className="insights-section-heading">
                  <h2>AI 使用</h2>
                  <Link href="/tasks" className="text-link">
                    执行记录
                    <ArrowUpRight size={14} />
                  </Link>
                </div>
                <div className="insights-usage-number">
                  {data.usage.calls}
                  <span>次调用</span>
                </div>
                <details className="usage-details">
                  <summary>
                    用量明细
                    <ChevronRight size={14} />
                  </summary>
                  <div className="key-value">
                    <span>输入 Token</span>
                    <strong>{data.usage.prompt_tokens.toLocaleString()}</strong>
                  </div>
                  <div className="key-value">
                    <span>输出 Token</span>
                    <strong>
                      {data.usage.completion_tokens.toLocaleString()}
                    </strong>
                  </div>
                  <div className="key-value">
                    <span>平均响应耗时</span>
                    <strong>
                      {data.usage.calls
                        ? `${(data.usage.average_duration_ms / 1000).toFixed(1)} 秒`
                        : "—"}
                    </strong>
                  </div>
                </details>
              </section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}

function ActivityChart({
  points,
}: {
  points: AnalyticsData["daily_activity"];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) =>
      setWidth(Math.max(280, Math.round(entries[0].contentRect.width))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const rows = points.slice(-14),
    top =
      Math.ceil(Math.max(4, ...rows.map((point) => point.attempts)) / 4) * 4;
  const height = 190,
    left = 30,
    bottom = 26,
    plotW = width - left - 10,
    plotH = height - bottom - 14,
    step = plotW / Math.max(rows.length, 1);
  const labelIndices = new Set(
    [0, 0.25, 0.5, 0.75, 1].map((fraction) =>
      Math.round((rows.length - 1) * fraction),
    ),
  );
  return (
    <div ref={ref} className="activity-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`近 14 天练习次数，共 ${rows.reduce((sum, point) => sum + point.attempts, 0)} 次`}
      >
        {[0, 1, 2, 3, 4].map((index) => {
          const y = height - bottom - (index / 4) * plotH;
          return (
            <g key={index}>
              <line
                x1={left}
                x2={width - 5}
                y1={y}
                y2={y}
                stroke="var(--border)"
              />
              <text x={left - 8} y={y + 4} textAnchor="end">
                {(top * index) / 4}
              </text>
            </g>
          );
        })}
        {rows.map((point, index) => {
          const h = (point.attempts / top) * plotH,
            x = left + index * step + step * 0.2;
          return (
            <g key={point.date}>
              <rect
                x={x}
                y={height - bottom - h}
                width={step * 0.6}
                height={h}
                fill="var(--accent)"
              >
                <title>
                  {point.date}：{point.attempts} 次练习
                </title>
              </rect>
              {labelIndices.has(index) && (
                <text x={x + step * 0.3} y={height - 6} textAnchor="middle">
                  {point.date.slice(5).replace("-", "/")}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {!rows.some((point) => point.attempts > 0) && (
        <p className="study-empty-note">近 14 天暂无练习记录。</p>
      )}
    </div>
  );
}
