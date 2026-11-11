"""User-scoped execution views. Never expose prompts, receipts or answer keys."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from backend.agent.policy import Profile, policy_from_checkpoint
from backend.agent.capabilities import capabilities
from backend.database import get_db
from backend.models.domain import Task, Trace
from backend.models.tutor import TutorEvent, TutorSession, TutorTurn
from backend.security import current_user

router = APIRouter(prefix="/api/agent", tags=["agent"])
DB, AUTH = Depends(get_db), Depends(current_user)
Kind = Literal["agent", "workflow"]


def summary(item, kind, session=None):
    return {
        "id": item.id, "kind": kind, "title": item.input[:80] if kind == "agent" else {"plan": "课程规划", "research": "资料研究", "ingest": "资料处理"}.get(item.kind, item.kind),
        "status": item.status, "course_id": session.course_id if session else getattr(item, "course_id", None),
        "session_id": item.session_id if kind == "agent" else None,
        "created_at": item.created_at, "updated_at": item.updated_at,
        "capability": (item.checkpoint or {}).get("agent", {}).get("capability", (item.checkpoint or {}).get("agent", {}).get("profile", "tutor")) if kind == "agent" else None,
    }


@router.get("/tools")
def tools(profile: Profile = "tutor", user=AUTH):
    from backend.tutor.tools import get_registry
    return {"profile": profile, "tools": get_registry().describe(profile)}


@router.get("/capabilities")
def capability_catalog(user=AUTH):
    return {"capabilities": capabilities()}


@router.get("/runs")
def runs(limit: int = Query(default=50, ge=1, le=100), user=AUTH, db=DB):
    result = []
    rows = db.query(TutorTurn, TutorSession).join(TutorSession, TutorTurn.session_id == TutorSession.id).filter(TutorTurn.user_id == user.id, TutorSession.user_id == user.id).order_by(TutorTurn.updated_at.desc()).limit(limit)
    result.extend(summary(turn, "agent", session) for turn, session in rows)
    result.extend(summary(task, "workflow") for task in db.query(Task).filter_by(user_id=user.id).order_by(Task.updated_at.desc()).limit(limit))
    return sorted(result, key=lambda item: item["updated_at"], reverse=True)[:limit]


def public_error(value):
    if not isinstance(value, dict):
        return None
    # Only structured errors produced by the runtime; no provider response body.
    return {"code": str(value.get("code", "execution_error"))[:80], "message": str(value.get("message", "执行失败"))[:400], "retryable": bool(value.get("retryable"))}


def agent_detail(db, user_id, identifier):
    turn = db.query(TutorTurn).filter_by(id=identifier, user_id=user_id).first()
    if not turn:
        raise HTTPException(404, "运行记录不存在。")
    session = db.query(TutorSession).filter_by(id=turn.session_id, user_id=user_id).first()
    if not session:
        raise HTTPException(404, "运行记录不存在。")
    events = db.query(TutorEvent).filter_by(turn_id=turn.id).order_by(TutorEvent.seq).all()
    spans, timeline, retries = {}, [], 0
    terminal = turn.status in {"completed", "failed", "cancelled"}
    for event in events:
        payload = event.payload or {}
        kind = event.type
        span_id = payload.get("span_id") or ("tool:" + str(payload["call_id"]) if payload.get("call_id") else None)
        public = None
        if kind == "model_start":
            spans[span_id] = {"id": span_id, "kind": "model", "name": str(payload.get("model", "模型"))[:120], "status": "running", "started_at": payload.get("started_at", event.created_at), "attempt": payload.get("attempt"), "metadata": {"protocol": payload.get("protocol"), "round": payload.get("round"), "scope": "main"}}
            public = {key: payload[key] for key in ("model", "round", "attempt") if key in payload}
        elif kind in {"model_end", "model_error"} and span_id:
            span = spans.setdefault(span_id, {"id": span_id, "kind": "model", "name": "模型"})
            span.update(status="failed" if kind == "model_error" else "succeeded", ended_at=payload.get("ended_at", event.created_at), duration_ms=payload.get("duration_ms"))
            if kind == "model_end":
                span["usage"] = payload.get("usage") if payload.get("usage_known") else None
            else:
                span["error"] = public_error(payload.get("error"))
                retries += int(bool(payload.get("will_retry")))
            public = {"status": span["status"], "duration_ms": span.get("duration_ms")}
        elif kind == "model_operation_start" and span_id:
            spans[span_id] = {"id": span_id, "parent_id": payload.get("parent_id"), "kind": "model", "name": str(payload.get("name", "内部模型调用"))[:120], "status": "running", "started_at": payload.get("started_at", event.created_at), "metadata": {"model": payload.get("model"), "scope": "internal"}}
            public = {"name": payload.get("name"), "status": "running"}
        elif kind == "model_operation" and span_id:
            span = spans.setdefault(span_id, {"id": span_id, "parent_id": payload.get("parent_id"), "kind": "model", "name": str(payload.get("name", "内部模型调用"))[:120], "metadata": {"model": payload.get("model"), "scope": "internal"}})
            span.update(status=payload.get("status", "succeeded"), ended_at=payload.get("ended_at", event.created_at), duration_ms=payload.get("duration_ms"), usage=payload.get("usage") if payload.get("usage_known") else None)
            if payload.get("status") == "failed":
                spans[span_id]["error"] = {"code": "model_operation_failed", "message": "内部模型调用失败。", "retryable": False}
            public = {"name": payload.get("name"), "status": payload.get("status"), "duration_ms": payload.get("duration_ms")}
        elif kind == "tool_start" and span_id:
            span = spans.setdefault(span_id, {"id": span_id, "kind": "tool", "name": str(payload.get("tool", "工具"))[:120]})
            span.update(status="running", started_at=payload.get("started_at", event.created_at), metadata={"access": payload.get("access")})
            public = {"tool": payload.get("tool")}
        elif kind == "tool_result":
            result = payload.get("result") or {}
            execution = result.get("_execution") or {}
            span_id = execution.get("span_id") or span_id
            if span_id:
                span = spans.setdefault(span_id, {"id": span_id, "kind": "tool", "name": str(payload.get("tool", "工具"))[:120]})
                span.update(status="failed" if result.get("error") else "succeeded", ended_at=execution.get("completed_at", event.created_at), duration_ms=execution.get("duration_ms"), attempt=execution.get("attempts"))
                if result.get("error"):
                    span["error"] = public_error(execution.get("error")) or {"code": "operation_rejected", "message": "工具操作未成功。", "retryable": False}
            public = {"tool": payload.get("tool"), "status": "failed" if result.get("error") else "succeeded"}
        elif kind == "tool_retry":
            retries += 1
            public = {"tool": payload.get("tool"), "attempt": payload.get("attempt"), "error": public_error(payload.get("error"))}
        elif kind == "tool_cached":
            if span_id in spans:
                spans[span_id]["cached"] = True
            public = {"tool": payload.get("tool"), "message": "复用持久化工具回执"}
        elif kind in {"retrieval_result", "memory_recalled", "memory_saved", "memory_forgotten", "memory_profile"}:
            allowed = ("query_count", "candidate_count", "source_count", "memory_count", "rewritten", "reranked")
            public = {key: payload[key] for key in allowed if key in payload and isinstance(payload[key], (int, bool))}
            if payload.get("strategy") in {"auto", "lexical", "enhanced"}:
                public["strategy"] = payload["strategy"]
            if payload.get("profile_status") in {"empty", "pending", "ready", "stale", "failed"}:
                public["profile_status"] = payload["profile_status"]
        elif kind == "context_budget":
            sid = "context:" + str(event.seq)
            spans[sid] = {"id": sid, "kind": "context", "name": "上下文预算估算", "status": "succeeded", "started_at": event.created_at, "metadata": {key: payload[key] for key in ("round", "estimated_tokens", "message_count", "tool_count", "estimation") if key in payload}}
            public = dict(spans[sid]["metadata"])
        elif kind in {"confirmation", "input_required"}:
            for span in reversed(list(spans.values())):
                if span["kind"] == "tool" and span.get("status") == "running":
                    span["status"] = "waiting"
                    break
            public = {"message": "等待明确确认" if kind == "confirmation" else "等待用户补充", "kind": payload.get("kind")}
        elif kind in {"status", "done", "error", "cancelled", "assessment", "question", "citations"}:
            public = {"message": {"status": "状态更新", "done": "轮次结束", "error": "本轮执行失败", "cancelled": "已取消", "assessment": "返回真实评分", "question": "返回练习题卡", "citations": "补充资料引用"}[kind]}
        if public is not None:
            timeline.append({"id": str(event.id), "seq": event.seq, "type": kind, "created_at": event.created_at, "payload": public})
    for span in spans.values():
        if span.get("status") == "running" and terminal:
            span["status"] = "cancelled" if turn.status == "cancelled" else "interrupted"
    models = [span for span in spans.values() if span["kind"] == "model"]
    tool_spans = [span for span in spans.values() if span["kind"] == "tool"]
    def tokens(key):
        return sum(span["usage"][key] for span in models) if models and all(isinstance((span.get("usage") or {}).get(key), int) for span in models) else None
    cp = turn.checkpoint or {}
    policy = policy_from_checkpoint(cp).model_dump()
    policy["allowed_tools"] = list(cp.get("agent", {}).get("allowed_tools", []))
    legacy_telemetry = cp.get("agent", {}).get("version", 1) < 2
    limitations = ["用量汇总本轮记录到的主循环及内部模型调用；缺少供应商用量的调用保持未知，不补零。", "上下文 Token 是保守估算；超时预算针对一次活跃执行，不包含等待用户的时间。"]
    if legacy_telemetry:
        limitations.append("该历史轮次早于嵌套模型关联，内部生成/评分/摘要请求可能未计入。")
    if not models:
        limitations.append("该历史运行未记录模型级 span，缺失指标显示为无记录。")
    result = {"run": summary(turn, "agent", session), "policy": policy, "spans": list(spans.values()), "events": timeline,
              "usage": {"prompt_tokens": tokens("prompt_tokens"), "completion_tokens": tokens("completion_tokens"), "model_calls": len(models) if models else None, "main_model_calls": sum((span.get("metadata") or {}).get("scope") != "internal" for span in models) if models else None, "internal_model_calls": sum((span.get("metadata") or {}).get("scope") == "internal" for span in models) if models else None, "tool_calls": len(tool_spans) if tool_spans else (0 if models else None), "retries": retries if models else None}, "limitations": limitations, "result": cp.get("agent", {}).get("result")}
    # Tool duration already includes child model calls. Count only root spans.
    durations = [span.get("duration_ms") for span in spans.values() if span["kind"] in {"tool", "model"} and not span.get("parent_id")]
    result["run"]["duration_ms"] = sum(durations) if durations and all(isinstance(d, int) for d in durations) else None
    return result


def workflow_detail(db, user_id, identifier):
    task = db.query(Task).filter_by(id=identifier, user_id=user_id).first()
    if not task:
        raise HTTPException(404, "运行记录不存在。")
    traces = db.query(Trace).filter_by(task_id=task.id, user_id=user_id).order_by(Trace.created_at).all()
    spans = [{"id": trace.id, "kind": "model" if trace.model else "workflow", "name": trace.step, "status": trace.status, "ended_at": trace.created_at, "duration_ms": trace.duration_ms,
              "usage": {"prompt_tokens": trace.prompt_tokens, "completion_tokens": trace.completion_tokens} if trace.model and (trace.prompt_tokens or trace.completion_tokens) else None,
              "metadata": {"model": trace.model} if trace.model else {}} for trace in traces]
    models = [span for span in spans if span["kind"] == "model"]
    known = models and all(span.get("usage") for span in models)
    return {"run": summary(task, "workflow"), "policy": None, "spans": spans,
            "events": [{"type": "status", "created_at": task.updated_at, "payload": {"status": task.status, "progress": task.progress}}],
            "usage": {"prompt_tokens": sum(span["usage"]["prompt_tokens"] for span in models) if known else None, "completion_tokens": sum(span["usage"]["completion_tokens"] for span in models) if known else None, "model_calls": len(models) if models else None, "tool_calls": None, "retries": None},
            "limitations": ["这是固定步骤 Workflow，保持与模型自主选工具的 Agent Loop 区分。", "历史 Trace 未记录的开始时间、重试与 Token 用量显示为无记录。"]}


def detail(db, user_id, kind, identifier):
    return agent_detail(db, user_id, identifier) if kind == "agent" else workflow_detail(db, user_id, identifier)


@router.get("/runs/{kind}/{identifier}")
def run_detail(kind: Kind, identifier: str, user=AUTH, db=DB):
    return detail(db, user.id, kind, identifier)


@router.get("/runs/{kind}/{identifier}/export")
def export(kind: Kind, identifier: str, user=AUTH, db=DB):
    value = detail(db, user.id, kind, identifier)
    # IDs are DB-generated UUIDs; the response only contains the sanitized view.
    return JSONResponse(value, headers={"Content-Disposition": f'attachment; filename="atlas-{kind}-{value["run"]["id"]}.json"'})
