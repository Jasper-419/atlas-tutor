"""Tool receipt ledger, policy checks, bounded read retries and safe recovery.

Business idempotency still belongs to domain transactions. A receipt avoids
repeating known completed work; it cannot manufacture exactly-once semantics
for an unacknowledged external side effect.
"""

import asyncio
import hashlib
import json
import time
from uuid import NAMESPACE_URL, uuid5
from fastapi import HTTPException
from pydantic import ValidationError
from backend.agent.policy import ExecutionError
from backend.llm import ModelError
from backend.models.domain import now
from backend.tutor.mutations import mutation_scope
from backend.agent.telemetry import child_span
from backend.agent.contracts import ToolOutcome


def error_result(error, **metadata):
    # Keep a human-readable top-level error for existing UI/business handlers.
    return {"error": error.message, "_execution": {"ok": False, "error": error.model_dump(), **metadata}}


def classify_error(exc):
    if isinstance(exc, ValidationError):
        message = "; ".join(".".join(map(str, e["loc"])) + " " + e["msg"] for e in exc.errors(include_input=False)[:3])
        return ExecutionError(code="invalid_arguments", message=message)
    if isinstance(exc, HTTPException):
        codes = {403: "permission_denied", 404: "resource_unavailable", 409: "state_conflict", 422: "invalid_arguments", 429: "rate_limited"}
        return ExecutionError(code=codes.get(exc.status_code, "service_error"), message=str(exc.detail), retryable=exc.status_code in {429, 502, 503, 504})
    if isinstance(exc, TimeoutError):
        return ExecutionError(code="tool_timeout", message="工具执行超过本次时间预算。", retryable=True)
    return ExecutionError(code=getattr(exc, "code", "model_error"), message=str(exc), retryable=bool(getattr(exc, "retryable", False)))


async def execute_tool(context, call, checkpoint, policy, emit, save, dispatch):
    from backend.tutor.tools import get_registry

    registry = get_registry()
    name = call.get("function", {}).get("name", "")
    identifier = call.get("id", "")
    try:
        arguments = json.loads(call["function"]["arguments"])
    except (ValueError, KeyError, TypeError):
        return error_result(ExecutionError(code="invalid_arguments", message="工具参数必须为有效 JSON 对象。"))
    if not identifier or not isinstance(arguments, dict):
        return error_result(ExecutionError(code="invalid_call", message="工具调用缺少唯一ID或有效参数。"))
    definition = registry.get(name)
    allowed = set(checkpoint.get("agent", {}).get("allowed_tools", registry.allowed_names(policy.profile)))
    fingerprint = hashlib.sha256(json.dumps({"name": name, "arguments": arguments}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ledger = checkpoint.setdefault("tool_receipts", {})
    previous = ledger.get(identifier)
    if previous and previous["arguments_digest"] != fingerprint:
        return error_result(ExecutionError(code="idempotency_conflict", message="同一工具调用ID不能用于不同参数。"))
    if previous is None and len(ledger) >= policy.max_tool_calls:
        return error_result(ExecutionError(code="tool_budget_exhausted", message="本轮工具调用预算已用完，请根据已取得的结果回答。"))
    if definition is None or name not in allowed or name not in registry.allowed_names(policy.profile):
        failure = ExecutionError(code="permission_denied" if definition else "unknown_tool", message="当前能力未授权该工具。" if definition else "不存在该工具。")
        result = error_result(failure, span_id="tool:" + identifier, attempts=0, duration_ms=0, completed_at=now())
        ledger[identifier] = {"name": name, "arguments_digest": fingerprint, "span_id": "tool:" + identifier, "status": "failed", "result": result, "attempts": 0}
        save(checkpoint)
        await emit("tool_start", {"tool": name, "call_id": identifier, "span_id": "tool:" + identifier, "started_at": now()})
        return result
    if previous and previous["status"] in {"succeeded", "failed", "uncertain"}:
        await emit("tool_cached", {"tool": name, "call_id": identifier, "span_id": previous["span_id"], "message": "复用已完成工具回执，未重复执行业务操作。"})
        return previous["result"]
    if previous and previous["status"] in {"waiting", "review_required"}:
        return previous["result"]
    if previous and previous["status"] == "running" and not definition.replay_safe:
        action = str(uuid5(NAMESPACE_URL, context.turn_id + ":uncertain:" + identifier))
        result = {"pause": {"action_id": action, "kind": "execution_review", "title": "核对中断的操作", "question": f"「{name}」曾开始但没有完整回执。请先核对已有结果，并说明是否需要重新执行。", "call_id": identifier}}
        previous.update(status="review_required", result=result)
        save(checkpoint)
        return result
    receipt = previous or {"name": name, "arguments_digest": fingerprint, "span_id": "tool:" + identifier, "attempts": 0}
    # A process interruption consumes a persisted recovery allowance. Even safe
    # reads/idempotent writes cannot regain unlimited attempts across claims.
    if previous and previous["status"] == "running":
        receipt["recoveries"] = receipt.get("recoveries", 0) + 1
    total_attempts = 1 + (policy.max_read_retries if definition.access == "read" else 0) + policy.max_tool_recoveries
    if receipt.get("recoveries", 0) > policy.max_tool_recoveries or receipt["attempts"] >= total_attempts:
        result = error_result(ExecutionError(code="recovery_budget_exhausted", message="该工具的中断恢复预算已用完，未继续执行；请核对已有结果后重新发起请求。"), span_id=receipt["span_id"], attempts=receipt["attempts"], completed_at=now())
        receipt.update(status="failed", result=result)
        save(checkpoint)
        return result
    receipt.update(status="running", started_at=receipt.get("started_at") or now())
    ledger[identifier] = receipt
    save(checkpoint)
    await emit("tool_start", {"tool": name, "call_id": identifier, "span_id": receipt["span_id"], "arguments": arguments, "started_at": receipt["started_at"], "access": definition.access})
    started = time.monotonic()
    max_attempts = min(1 + (policy.max_read_retries if definition.access == "read" else 0), total_attempts - receipt["attempts"])
    result, failure = None, None
    for attempt in range(max_attempts):
        receipt["attempts"] += 1
        save(checkpoint)
        try:
            async with asyncio.timeout(definition.timeout_seconds):
                with mutation_scope(context.turn_id, context.token), child_span(receipt["span_id"]):
                    result = await dispatch(context, call)
            failure = None
            break
        except (ValidationError, HTTPException, ModelError, TimeoutError) as exc:
            failure = classify_error(exc)
            if not failure.retryable or attempt + 1 >= max_attempts:
                break
            await emit("tool_retry", {"tool": name, "call_id": identifier, "span_id": receipt["span_id"], "attempt": receipt["attempts"] + 1, "error": failure.model_dump()})
            await asyncio.sleep(min(0.2 * (attempt + 1), 0.5))
    metadata = {"span_id": receipt["span_id"], "attempts": receipt["attempts"], "duration_ms": int((time.monotonic() - started) * 1000), "completed_at": now(), "access": definition.access}
    if failure:
        result = error_result(failure, **metadata)
    else:
        try:
            outcome = ToolOutcome.from_handler(result)
        except (ValueError, TypeError):
            outcome = ToolOutcome(success=False, error=ExecutionError(code="invalid_tool_result", message="工具结果不符合JSON控制协议。"))
        result = outcome.legacy()
        if outcome.error:
            result["_execution"] = {"ok": False, "error": outcome.error.model_dump(), **metadata}
        elif not outcome.pause:
            result["_execution"] = {"ok": True, **metadata}
    receipt.update(status="waiting" if result.get("pause") else "failed" if result.get("error") else "succeeded", result=result, **metadata)
    save(checkpoint)
    return result


def resume_receipt(checkpoint, call, result):
    receipt = checkpoint.get("tool_receipts", {}).get(call["id"])
    if receipt:
        if receipt.get("status") == "review_required":
            # A human message is evidence to consider, not a tool completion.
            result = {**result, **error_result(ExecutionError(code="uncertain_outcome", message="中断操作结果尚未由工具核实。先查询现有状态，不得将本条用户说明当作执行成功回执。"), span_id=receipt["span_id"], resumed=True)}
            receipt.update(status="uncertain", result=result, completed_at=now())
            return result
        receipt.update(status="succeeded", result=result, completed_at=now())
        return {**result, "_execution": {"ok": True, "span_id": receipt["span_id"], "duration_ms": receipt.get("duration_ms"), "resumed": True}}
    return result
