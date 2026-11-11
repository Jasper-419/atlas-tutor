"""Bounded shared agent loop, recoverable independently of a browser connection."""

import asyncio
import copy
import hashlib
import json
import logging
import time
from contextlib import suppress

from backend.agent.execution import execute_tool, resume_receipt
from backend.agent.policy import policy_from_checkpoint, TransientModelError
from backend.agent.capabilities import get_capability
from backend.agent.telemetry import trace_scope
from backend.connections import resolve_model_config
from backend.database import SessionLocal
from backend.llm import ModelError
from backend.models.tutor import TutorSession, TutorTurn
from backend.models.domain import now
from backend.tutor import store
from backend.tutor.citations import CITATION_GUIDANCE, has_unknown_citations, normalize_citation_labels
from backend.tutor.context import budget_messages, build_context, estimate_tokens
from backend.tutor.mutations import mutation_scope
from backend.tutor.providers import model_round
from backend.tutor.tools import ToolContext, execute, get_registry

logger = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 6
TURN_TIMEOUT_SECONDS = 480


def citation_key(item):
    # A chunk may span pages; source reads may also return only a bounded
    # prefix. Reuse a number only for the same exact evidence and locator.
    return json.dumps([
        item.get("source_id") or item.get("url") or item.get("title"),
        item.get("source_version", 1), item.get("chunk_index", "document"),
        item.get("page_start"), item.get("page_end"), item.get("section"),
        hashlib.sha256((item.get("excerpt") or "").encode()).hexdigest(),
    ], ensure_ascii=False, separators=(",", ":"))


def current(identifier, token):
    with SessionLocal() as db:
        turn = store.lock_turn(db, identifier, token)
        return (
            copy.deepcopy(turn.checkpoint or {}),
            turn.session_id,
            turn.user_id,
            turn.output,
        )


def finish(identifier, token, status="completed", error=None):
    with SessionLocal() as db:
        store.write_lock(db)
        turn = store.lock_turn(db, identifier, token)
        turn.status, turn.error = status, error
        turn.lease_until = turn.worker_token = None
        turn.pending_action = None
        cp = copy.deepcopy(turn.checkpoint or {})
        agent = cp.setdefault("agent", {})
        capability = get_capability(agent.get("capability", agent.get("profile", "tutor")))
        agent["result"] = capability.result(cp, status)
        turn.checkpoint = cp
        if error:
            store.add_event(db, turn, "error", {"detail": error})
        result = store.serialize_turn(turn)
        result["last_seq"] = turn.last_seq + 1
        store.add_event(db, turn, "done", {"turn": result})
        session = db.get(TutorSession, turn.session_id)
        if session:
            session.updated_at = turn.updated_at
        db.commit()


def pause(identifier, token, cp, action):
    with SessionLocal() as db:
        store.write_lock(db)
        turn = store.lock_turn(db, identifier, token)
        turn.checkpoint = cp
        turn.pending_action = action
        turn.status = (
            "waiting_confirmation"
            if action["kind"] in {"path_change", "question_repair"}
            else "waiting_input"
        )
        turn.lease_until = turn.worker_token = None
        store.add_event(
            db,
            turn,
            "confirmation"
            if action["kind"] in {"path_change", "question_repair"}
            else "input_required",
            store.public_action(action),
        )
        store.add_event(db, turn, "status", {"status": turn.status})
        db.commit()


async def run(identifier, token):
    _, _, user_id, _ = current(identifier, token)
    with trace_scope(identifier, token, user_id):
        await run_turn(identifier, token)


async def run_turn(identifier, token):
    cp, session_id, user_id, output = current(identifier, token)
    if cp.get("stage") == "complete":
        finish(identifier, token)
        return
    policy = policy_from_checkpoint(cp)
    capability = get_capability(cp.get("agent", {}).get("capability", policy.profile))
    registry = get_registry()
    if not cp.get("agent"):
        cp["agent"] = {"version": 2, "capability": capability.name, "profile": policy.profile, "policy": policy.model_dump(), "allowed_tools": sorted(registry.allowed_names(policy.profile))}
        store.checkpoint(identifier, token, cp)
    config = resolve_model_config(user_id)
    if not config.configured:
        raise ModelError("尚未连接模型，请在设置 → AI 连接中添加 API。")

    async def emit(kind, payload):
        if kind == "citations":
            known = cp.setdefault("citations", [])

            positions = {citation_key(item): index for index, item in enumerate(known)}
            for item in payload.get("citations", []):
                identifier_key = citation_key(item)
                if identifier_key not in positions:
                    positions[identifier_key] = len(known)
                    known.append(dict(item))
                index = positions[identifier_key]
                item["citation"] = index + 1
                known[index]["citation"] = index + 1
                known[index]["id"] = (
                    "ref-" + hashlib.sha256(identifier_key.encode()).hexdigest()[:16]
                )
            payload = {"citations": known}
            store.emit(identifier, kind, payload, token, cp)
        else:
            store.emit(identifier, kind, payload, token)

    context = ToolContext(identifier, token, emit, profile=policy.profile, checkpoint=cp)

    def save(checkpoint):
        store.checkpoint(identifier, token, checkpoint)
    if not cp.get("messages"):
        if cp.get("grade_input") and not cp.get("assessment"):
            from backend.learning import submit_answer

            with SessionLocal() as db:
                data = cp["grade_input"]
                with mutation_scope(identifier, token):
                    result = await submit_answer(
                        db,
                        user_id,
                        data["exercise_id"],
                        data["answer"],
                        data["request_id"],
                    )
            cp["assessment"] = result
            store.emit(identifier, "assessment", result, token, cp)
        messages, citations = await build_context(session_id, identifier, on_event=emit)
        cp.update(messages=messages, rounds=0, stage="model", stable_output=output)
        store.checkpoint(identifier, token, cp)
        if citations:
            await emit("citations", {"citations": citations})
    elif cp.get("stage") == "model" and output != cp.get("stable_output", ""):
        # The interrupted provider call never completed. Its text can be replayed
        # from events, then explicitly replaced before a safe new model call.
        output = cp.get("stable_output", "")
        await emit("content_reset", {"text": output})
    await emit("status", {"status": "running", "message": "正在结合你的学习情况处理"})
    while True:
        if cp.get("stage") == "tools":
            calls = cp["pending_calls"]
            for index in range(cp.get("tool_index", 0), len(calls)):
                call = calls[index]
                name = call["function"]["name"]
                cp["tool_index"] = index
                store.checkpoint(identifier, token, cp)
                if "resume_result" in cp:
                    result = resume_receipt(cp, call, cp.pop("resume_result"))
                else:
                    result = await execute_tool(context, call, cp, policy, emit, save, execute)
                if result.get("pause"):
                    pause(identifier, token, cp, result["pause"])
                    return
                cp["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                cp["tool_index"] = index + 1
                store.emit(
                    identifier,
                    "tool_result",
                    {"tool": name, "call_id": call["id"], "result": result},
                    token,
                    cp,
                )
            cp["stage"] = "model"
            cp.pop("pending_calls", None)
            cp.pop("tool_index", None)
            if output and not output.endswith("\n\n"):
                await emit("content", {"text": "\n\n"})
                output += "\n\n"
            cp["stable_output"] = output
            store.checkpoint(identifier, token, cp)
        allowed = set(cp["agent"]["allowed_tools"])
        available = [schema for schema in registry.schemas(policy.profile) if schema["function"]["name"] in allowed] if cp["rounds"] < policy.max_rounds and len(cp.get("tool_receipts", {})) < policy.max_tool_calls else []
        messages = budget_messages(cp["messages"], available)
        messages.append(capability.prepare(cp))
        messages = messages + [{"role": "system", "content": "本轮能力为 " + policy.profile + "，仅使用提供的工具。工具返回 error 时不得声称成功；execution_review 表示中断操作没有完整回执，先核对现有状态，不得仅凭用户继续就假定操作已成功。"}]
        if cp.get("citations"):
            messages.append({"role": "system", "content": CITATION_GUIDANCE})
        await emit("context_budget", {"round": cp["rounds"] + 1, "estimated_tokens": estimate_tokens(messages) + estimate_tokens(available), "message_count": len(messages), "tool_count": len(available), "estimation": True})
        if not available:
            messages = messages + [
                {
                    "role": "system",
                    "content": "本次工具调用预算已用完，请根据已获得的真实结果简洁总结，明确尚未完成的事项，不得声称执行了未成功的操作。",
                }
            ]
        result, buffer, last_flush = None, "", time.monotonic()
        round_output = output
        round_key = str(cp["rounds"])
        attempts = cp["agent"].setdefault("model_attempts", {})
        # Persist the retry allowance before issuing the request. Process recovery
        # cannot reset the allowance and produce an unlimited provider retry loop.
        while True:
            attempt = attempts.get(round_key, 0) + 1
            if attempt > 1 + policy.max_model_retries:
                raise ModelError("本轮模型请求与恢复预算已用完，请重新发起消息。")
            attempts[round_key] = attempt
            save(cp)
            span_id = f"model:{cp['rounds']}:{attempt}"
            started = time.monotonic()
            await emit("model_start", {"span_id": span_id, "round": cp["rounds"] + 1, "attempt": attempt, "model": config.model, "protocol": config.protocol, "started_at": now()})
            received_text, usage, usage_known = False, None, False
            try:
                async for part in model_round(config, messages, available, user_id):
                    if part["kind"] == "text":
                        received_text = received_text or bool(part["text"])
                        buffer += part["text"]
                        if len(buffer) >= 100 or time.monotonic() - last_flush >= 0.3:
                            await emit("content", {"text": buffer})
                            output += buffer
                            buffer, last_flush = "", time.monotonic()
                    else:
                        result = part["message"]
                        usage_known = part.get("usage_known", bool(part.get("usage")))
                        usage = part.get("usage") if usage_known else None
                if result is None:
                    raise ModelError("模型没有返回完整的轮次。")
            except ModelError as exc:
                retry = isinstance(exc, TransientModelError) and not received_text and attempt <= policy.max_model_retries
                await emit("model_error", {"span_id": span_id, "attempt": attempt, "duration_ms": int((time.monotonic() - started) * 1000), "ended_at": now(), "error": {"code": getattr(exc, "code", "model_error"), "message": str(exc), "retryable": retry}, "will_retry": retry})
                if retry:
                    await asyncio.sleep(0.3 * attempt)
                    continue
                raise
            await emit("model_end", {"span_id": span_id, "duration_ms": int((time.monotonic() - started) * 1000), "ended_at": now(), "usage": usage, "usage_known": usage_known})
            break
        if buffer:
            await emit("content", {"text": buffer})
            output += buffer
        if result is None:
            raise ModelError("模型没有返回完整的轮次。")
        cp["messages"].append(result)
        cp["rounds"] += 1
        cp["stable_output"] = output
        if not result.get("tool_calls"):
            if not capability.ready_to_finish(cp):
                # An unchecked final answer must not become the recorded outcome.
                output = round_output
                cp["stable_output"] = output
                await emit("content_reset", {"text": output})
                if not available:
                    raise ModelError("解题预算已用完，计划仍有未完成或未核验的步骤。已保留实际执行记录。")
                cp["messages"].append({"role": "system", "content": "当前solve计划尚未完成。必须依据实际执行凭据完成步骤并调用solve_finish；不能仅用文字声称完成。工具失败时先修正，确实无法完成时保留未完成状态。"})
                store.checkpoint(identifier, token, cp)
                continue
            citations = cp.get("citations", [])
            answer = result.get("content")
            suffix = normalize_citation_labels(output[len(round_output):], citations)
            if isinstance(answer, str):
                result["content"] = normalize_citation_labels(answer, citations)
                if policy.profile == "qa" and citations and has_unknown_citations(answer, citations):
                    if not cp["agent"].get("citation_retry") and cp["rounds"] <= policy.max_rounds:
                        cp["agent"]["citation_retry"] = True
                        cp["messages"].append({
                            "role": "system",
                            "content": (
                                "上一版引用了本轮未登记的编号。请重新核对资料原文与 citation 字段后作答。"
                                "表格中的事项编号和页码不能作为引用编号。"
                                "如果找不到支持结论的已登记来源，请说明资料不足。"
                            ),
                        })
                        output = round_output
                        cp["stable_output"] = output
                        store.emit(identifier, "content_reset", {"text": output}, token, cp)
                        continue
                    suffix = "未能核对本次回答所用的资料引用，请尝试指定资料或缩小问题范围。"
                    result["content"] = suffix
            final_output = round_output + suffix
            cp.update(stage="complete", stable_output=final_output)
            if final_output != output:
                store.emit(identifier, "content_reset", {"text": final_output}, token, cp)
            else:
                store.checkpoint(identifier, token, cp)
            finish(identifier, token)
            return
        if not available:
            raise ModelError("模型在工具预算结束后仍请求操作，本轮已停止。")
        cp.update(stage="tools", pending_calls=result["tool_calls"], tool_index=0)
        store.checkpoint(identifier, token, cp)


async def lease_watch(identifier, token):
    while True:
        await asyncio.sleep(2)
        if not store.heartbeat(identifier, token):
            raise store.LostLease()


async def run_claim(identifier, token):
    execution = asyncio.create_task(run(identifier, token))
    watch = asyncio.create_task(lease_watch(identifier, token))
    try:
        cp, *_ = current(identifier, token)
        async with asyncio.timeout(policy_from_checkpoint(cp).timeout_seconds):
            done, _ = await asyncio.wait(
                [execution, watch], return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                await task
    except (store.LostLease, asyncio.CancelledError):
        pass
    except TimeoutError:
        with suppress(store.LostLease):
            finish(
                identifier,
                token,
                "failed",
                "本轮处理超时，已保存过程。请缩小问题范围后重试。",
            )
    except (ModelError, ValueError) as exc:
        with suppress(store.LostLease):
            finish(identifier, token, "failed", str(exc))
    except Exception:
        logger.exception("Tutor turn failed (turn_id=%s)", identifier)
        with suppress(store.LostLease):
            finish(identifier, token, "failed", "本轮处理失败，过程已保存，请重试。")
    finally:
        for task in (execution, watch):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, store.LostLease, Exception):
                await task
        # Graceful shutdown releases a running lease; a killed process is
        # recovered when its persisted lease expires. Never revive cancelled work.
        with SessionLocal() as db:
            db.query(TutorTurn).filter_by(
                id=identifier, worker_token=token, status="running"
            ).update(
                {"status": "queued", "worker_token": None, "lease_until": None},
                synchronize_session=False,
            )
            db.commit()


async def worker_loop(stop):
    jobs = set()
    try:
        while not stop.is_set():
            jobs = {job for job in jobs if not job.done()}
            if len(jobs) < 2:
                claimed = store.claim()
                if claimed:
                    jobs.add(asyncio.create_task(run_claim(*claimed)))
                    continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.6)
            except TimeoutError:
                pass
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
