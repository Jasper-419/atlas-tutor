import { Markdown } from "./ui";
import "./solve-result.css";

type SolveCheck = { expression?: string; expected?: unknown; actual?: unknown; passed?: boolean };
type SolveExecution = { id?: string; evidence_id?: string; step_id?: string; plan_version?: number; status?: string; stdout?: string; error?: string | { message?: string }; checks?: SolveCheck[]; code?: string };
type SolveStep = { id: string; title: string; method?: string; status?: string; explanation?: string; verification?: { evidence_id?: string; plan_version?: number; checks_passed?: number | boolean } };
export type PublicSolveResult = { kind: "solve"; action?: string; status?: string; error?: string; plan?: { version?: number; goal?: string; status?: string; summary?: string; steps?: SolveStep[] }; execution?: SolveExecution; executions?: SolveExecution[]; summary?: string; message?: string; unverified?: string[] };

export function solvePayload(value: unknown): PublicSolveResult | null {
  return value && typeof value === "object" && (value as Record<string, unknown>).kind === "solve" ? value as PublicSolveResult : null;
}
const statuses: Record<string, string> = { pending: "待处理", running: "处理中", completed: "已完成", verified: "执行校验", reasoned: "推理说明", unverified: "尚未验证", failed: "未通过", error: "执行出错", succeeded: "执行成功", passed: "检查通过", partial: "部分完成", skipped: "已跳过", rejected: "执行被拒绝", resource_limit: "达到执行限制", timeout: "执行超时" };
const textValue = (value: unknown) => typeof value === "string" ? value : value === undefined ? "无记录" : JSON.stringify(value);

export function SolveResult({ result, detailed = false, evidence = [] }: { result: PublicSolveResult; detailed?: boolean; evidence?: SolveExecution[] }) {
  const plan = result.plan;
  const executions = [...(result.executions || []), ...(result.execution ? [result.execution] : [])];
  return <section className={`atlas-solve-result${detailed ? " is-detailed" : ""}`} aria-label={detailed ? "解题执行记录" : "解题计划"}>
    {plan && <><div className="atlas-solve-heading"><strong>{detailed ? "解题计划" : "分步求解"}</strong>{plan.version !== undefined && <span>第 {plan.version} 版</span>}</div>{plan.goal && <p className="atlas-solve-goal">{plan.goal}</p>}<ol className="atlas-solve-steps">{plan.steps?.map((step) => {
      // A verified status is issued only after the backend binds a successful execution receipt.
      const receipt = [...executions, ...evidence].filter((item) => item.step_id === step.id && item.plan_version === plan.version).at(-1);
      const evidenceVerified = receipt?.status === "passed" && !!receipt.checks?.length && receipt.checks.every((check) => check.passed === true);
      const boundVerification = !!step.verification?.evidence_id && step.verification.plan_version === plan.version && !!step.verification.checks_passed;
      const verified = step.method === "python" && step.status === "verified" && (evidenceVerified || boundVerification);
      const label = verified ? "执行校验" : step.status === "reasoned" ? "推理说明" : step.status === "verified" ? "尚未验证" : statuses[step.status || ""] || "待处理";
      return <li key={step.id}><div><span>{step.title}</span><small className={verified ? "is-verified" : ""}>{label}</small></div>{step.explanation && <p>{step.explanation}</p>}</li>;
    })}</ol></>}
    {detailed && executions.map((execution, index) => <Execution key={execution.id || execution.evidence_id || index} execution={execution} />)}
    {result.status === "error" && result.error && <p className="atlas-solve-error">{result.error}</p>}
    {detailed && (result.summary || result.message) && <Markdown>{result.summary || result.message || ""}</Markdown>}
    {!!result.unverified?.length && <p className="atlas-solve-unverified">尚未验证：{result.unverified.join("；")}</p>}
  </section>;
}

function Execution({ execution }: { execution: SolveExecution }) {
  const checks = execution.checks || [];
  const error = typeof execution.error === "string" ? execution.error : execution.error?.message;
  return <div className="atlas-solve-execution">
    <strong>Python · {statuses[execution.status || ""] || execution.status || "状态无记录"}</strong>
    {typeof execution.stdout === "string" && <div><span>实际输出</span><pre>{execution.stdout || "（无输出）"}</pre></div>}
    {error && <div className="atlas-solve-error"><span>执行错误</span><pre>{error}</pre></div>}
    {checks.length > 0 && <ul className="atlas-solve-checks">{checks.map((check, index) => <li key={index}><div><code>{check.expression || `检查 ${index + 1}`}</code><span className={check.passed === true ? "is-verified" : ""}>{check.passed === true ? "通过" : check.passed === false ? "未通过" : "无记录"}</span></div><p>预期 {textValue(check.expected)} · 实际 {textValue(check.actual)}</p></li>)}</ul>}
    {execution.code && <details><summary>运行代码</summary><pre>{execution.code}</pre></details>}
  </div>;
}
