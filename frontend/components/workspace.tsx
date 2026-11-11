"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, BookOpen, Check, LockKeyhole, FileQuestion, RefreshCw, Loader2, PanelRight } from "lucide-react";
import { post, uid, useResource } from "@/lib/api";
import type { CourseDetail, KnowledgeNode, Citation, Exercise, Attempt } from "@/lib/types";
import { useAtlas } from "./atlas-app";
import { Loading, ErrorBox, Markdown, Citations, Empty } from "./ui";
import { Tutor } from "./tutor";
import { QuestionDispute } from "./learning-panels";

export function WorkspaceScreen({ courseId, nodeId }: { courseId: string; nodeId: string }) {
  const { data: course, error, loading, reload } = useResource<CourseDetail>(`/courses/${courseId}`);
  const [reading, setReading] = useState(false);
  const [tab, setTab] = useState("lesson");
  const [content, setContent] = useState<string | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);
  const [lessonError, setLessonError] = useState("");
  const [lessonStale, setLessonStale] = useState(false);
  const [tutorRequest, setTutorRequest] = useState<{ id: string; content: string } | null>(null);
  const [exerciseRevision, setExerciseRevision] = useState(0);
  const changed = useCallback(() => { reload(); setExerciseRevision((value) => value + 1); }, [reload]);
  const node = course?.nodes.find((item) => item.id === nodeId);
  useEffect(() => { setContent(node?.content || null); setCitations(node?.lesson_citations || []); setLessonStale(!!(node as (KnowledgeNode & { lesson_stale?: boolean }) | undefined)?.lesson_stale); }, [node?.id, node?.content, node?.lesson_citations, (node as (KnowledgeNode & { lesson_stale?: boolean }) | undefined)?.lesson_stale]);
  if (loading) return <Loading label="正在恢复学习进度…" />;
  if (error || !course || !node) return <ErrorBox message={error || "找不到这个知识节点"} retry={reload} />;
  if (node.status === "locked") return <Empty title="先把前面的知识连接起来" description="掌握前置节点后，本节会自动解锁。"><Link href={`/courses/${courseId}`} className="button">查看学习路径</Link></Empty>;
  const lessonBody = content?.replace(/^\s*#{1,2}[\t ]+(.+?)[\t ]*\r?\n/, (heading, title: string) => title.trim() === node.title.trim() ? "" : heading);
  return <div className="tutor-learning">
    <header className="tutor-learning-top"><Link href={`/courses/${courseId}`} title={course.title}><ArrowLeft size={15} /><span>{course.title} / {node.title}</span></Link><button className="button" aria-expanded={reading} aria-controls="tutor-reading" onClick={() => setReading(!reading)}><PanelRight size={16} />{reading ? "收起学习资料" : "讲义与路径"}</button></header>
    <div className={`tutor-learning-body ${reading ? "with-reading" : ""}`}>
      <Tutor courseId={courseId} nodeId={nodeId} onChanged={changed} incomingRequest={tutorRequest} />
      <aside className="tutor-learning-reading" id="tutor-reading" hidden={!reading} aria-label="课程学习资料">
        <h2>{node.title}</h2><p>{node.objective || node.summary}</p>
        <div className="tabs"><button className={tab === "lesson" ? "active" : ""} onClick={() => setTab("lesson")}><BookOpen size={14} />讲义</button><button className={tab === "practice" ? "active" : ""} onClick={() => setTab("practice")}><FileQuestion size={14} />练习</button><button className={tab === "path" ? "active" : ""} onClick={() => setTab("path")}>学习路径</button></div>
        {tab === "lesson" && <>{lessonError && <ErrorBox message={lessonError} />}{lessonStale && <div className="lesson-stale-notice"><span>课程资料已有新版本，这份讲义引用的是历史资料。</span><button className="button" disabled={busy} onClick={async () => { setBusy(true); setLessonError(""); try { const lesson = await post<{ content: string; citations: Citation[]; stale: boolean }>(`/nodes/${nodeId}/lesson/regenerate`); setContent(lesson.content); setCitations(lesson.citations); setLessonStale(lesson.stale); reload(); } catch (e) { setLessonError((e as Error).message); } finally { setBusy(false); } }}>{busy ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}{busy ? "正在重新生成…" : "重新生成讲义"}</button></div>}{content ? <><Markdown>{lessonBody || content}</Markdown><Citations items={citations} /></> : <div className="generate-lesson"><p>可以在对话中请 Atlas 讲解，也可以展开本节讲义。</p><button className="button" disabled={busy} onClick={async () => { setBusy(true); setLessonError(""); try { const lesson = await post<{ content: string; citations: Citation[] }>(`/nodes/${nodeId}/lesson`); setContent(lesson.content); setCitations(lesson.citations); reload(); } catch (e) { setLessonError((e as Error).message); } finally { setBusy(false); } }}>{busy ? <Loader2 size={15} className="spin" /> : <BookOpen size={15} />}{busy ? "正在准备讲义…" : "生成本节讲义"}</button></div>}</>}
        {tab === "practice" && <ExercisePanel node={node} courseId={courseId} revision={exerciseRevision} onEvaluated={changed} onDispute={(content) => setTutorRequest({ id: uid(), content })} />}
        {tab === "path" && <nav aria-label="课程知识节点">{course.nodes.map((item, index) => <Link key={item.id} href={item.status === "locked" ? "#" : `/courses/${courseId}/learn/${item.id}`} aria-disabled={item.status === "locked"} aria-current={item.id === nodeId ? "step" : undefined} className={`syllabus-node ${item.id === nodeId ? "selected" : ""} ${item.status === "locked" ? "disabled" : ""}`} onClick={(e) => { if (item.status === "locked") e.preventDefault(); }}><span className="syllabus-dot">{item.status === "mastered" ? <Check size={12} /> : item.status === "locked" ? <LockKeyhole size={11} /> : index + 1}</span><span>{item.title}<small>{item.estimated_minutes} 分钟</small></span></Link>)}</nav>}
      </aside>
    </div>
  </div>;
}

function ExercisePanel({
  node,
  courseId,
  onEvaluated,
  onDispute,
  revision,
}: {
  node: KnowledgeNode;
  courseId: string;
  onEvaluated: () => void;
  onDispute: (prompt: string) => void;
  revision: number;
}) {
  const {
      data: exercises,
      error: loadError,
      loading,
      reload,
    } = useResource<Exercise[]>(`/nodes/${node.id}/exercises`),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const { data: attempts, reload: reloadAttempts } = useResource<(Attempt & { voided?: boolean })[]>(
    `/attempts?course_id=${courseId}&include_voided=true`,
  );
  const previousRevision = useRef(revision);
  useEffect(() => { if (previousRevision.current !== revision) { previousRevision.current = revision; reload(); reloadAttempts(); } }, [revision, reload, reloadAttempts]);
  return (
    <div className="exercise-panel">
      <div className="exercise-intro">
        <h2>把理解，试着说出来。</h2>
        <p>练习结果会更新掌握度、记录薄弱点，并调整后续复习。</p>
      </div>
      {loading ? (
        <Loading label="正在读取练习…" />
      ) : loadError ? (
        <ErrorBox message={loadError} retry={reload} />
      ) : exercises?.length ? (
        <>
          {exercises.map((x, i) => (
            <ExerciseCard
              exercise={x}
              courseId={courseId}
              index={i}
              key={x.id}
              onEvaluated={onEvaluated}
              onDispute={onDispute}
              initialResult={attempts?.find((a) => a.exercise_id === x.id)}
            />
          ))}
        </>
      ) : (
        <Empty
          title="为这节生成一些练习"
          description="题目将围绕当前知识节点，并保存到这门课程中。"
        />
      )}
      {error && <ErrorBox message={error} />}
      <button
        className="button generate-exercises"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await post(`/nodes/${node.id}/exercises`);
            reload();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? (
          <Loader2 className="spin" size={15} />
        ) : (
          <RefreshCw size={15} />
        )}
        {exercises?.length ? "重新加载练习" : "生成本节练习"}
      </button>
    </div>
  );
}
function ExerciseCard({
  exercise: x,
  courseId,
  index,
  onEvaluated,
  initialResult,
  onDispute,
}: {
  exercise: Exercise;
  courseId: string;
  index: number;
  onEvaluated: () => void;
  initialResult?: Attempt & { voided?: boolean };
  onDispute: (prompt: string) => void;
}) {
  const { notify } = useAtlas(),
    [answer, setAnswer] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [result, setResult] = useState<(Attempt & { voided?: boolean }) | null>(null),
    requestId = useRef(uid());
  useEffect(() => {
    if (initialResult) {
      setResult(initialResult);
      setAnswer(initialResult.answer);
    }
  }, [initialResult]);
  const voided = !!result?.voided || !!(x as Exercise & { voided?: boolean }).voided;
  return (
    <article className="exercise-card">
      <div className="exercise-label">
        <span>练习 {String(index + 1).padStart(2, "0")}</span>
        <span>{x.type === "choice" ? "选择题" : "开放问答"}</span>
      </div>
      <Markdown>{x.prompt}</Markdown>
      {voided && <p className="muted small">已作废，不计掌握度</p>}
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const a = await post<Attempt>(`/exercises/${x.id}/attempts`, {
              answer,
              request_id: requestId.current,
            });
            setResult(a);
            onEvaluated();
            notify(
              a.passed
                ? "理解又连接了一点，掌握度已更新。"
                : "反馈已保存，薄弱点已加入学习记忆。",
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {x.type === "choice" ? (
          <div className="exercise-options">
            {x.options.map((option, i) => (
              <label
                className={`exercise-option ${answer === option ? "selected" : ""}`}
                key={i}
              >
                <input
                  type="radio"
                  name={`answer-${x.id}`}
                  value={option}
                  checked={answer === option}
                  onChange={() => setAnswer(option)}
                  disabled={!!result || voided}
                />
                <span className="option-letter">
                  {String.fromCharCode(65 + i)}
                </span>
                <span>{option}</span>
              </label>
            ))}
          </div>
        ) : (
          <label className="answer-field">
            你的解释
            <textarea
              rows={5}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              disabled={!!result || voided}
              placeholder="试着用自己的话说明…"
              required
              maxLength={10000}
            />
          </label>
        )}
        {error && <ErrorBox message={error} />}
        {!result && !voided && (
          <button className="button primary" disabled={busy || !answer.trim()}>
            {busy ? (
              <>
                <Loader2 size={15} className="spin" />
                正在评估…
              </>
            ) : (
              "提交，看看理解得怎样"
            )}
          </button>
        )}
      </form>
      <QuestionDispute exerciseId={x.id} disabled={busy || voided} onRequest={onDispute} />
      {result && !voided && (
        <div
          className={`exercise-feedback ${result.passed ? "passed" : "needs-review"}`}
        >
          <div className="feedback-heading">
            <strong>
              {result.passed ? "这次理解得不错。" : "这里值得再想一想。"}
            </strong>
            <span>
              {Math.round(result.score)} <small>/ 100</small>
            </span>
          </div>
          <Markdown>{result.feedback}</Markdown>
          {result.correct_answer && (
            <details>
              <summary>参考答案与解释</summary>
              <Markdown>{result.correct_answer}</Markdown>
            </details>
          )}
          <div className="feedback-next">
            <span>当前节点掌握度 {Math.round(result.mastery)}%</span>
            {result.next_node_id && result.next_node_id !== x.node_id && (
              <Link
                href={`/courses/${courseId}/learn/${result.next_node_id}`}
                className="text-link"
              >
                前往下一节 <ArrowRight size={14} />
              </Link>
            )}
            <button
              className="text-button"
              onClick={() => {
                setResult(null);
                setAnswer("");
                requestId.current = uid();
              }}
            >
              再试一次
            </button>
          </div>
        </div>
      )}
    </article>
  );
}
