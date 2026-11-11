"""User-selected model adapter with real usage tracing and honest failures."""

import json
import re
import time
import math
import httpx
from backend.config import get_settings
from backend.database import session_scope
from backend.models import Trace
from backend.connections import resolve_model_config
from backend.model_providers import (
    ModelError,
    request_completion,
    request_parts,
    check_status,
    stream_event,
    usage_tokens,
)


def record_trace(
    user_id,
    step,
    status="succeeded",
    detail="",
    task_id=None,
    duration_ms=None,
    prompt_tokens=0,
    completion_tokens=0,
    model=None,
    operation_id=None,
):
    with session_scope() as db:
        db.add(
            Trace(
                user_id=user_id,
                task_id=task_id,
                step=step,
                status=status,
                detail=detail[:1500],
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=model,
            )
        )
    from backend.agent.telemetry import record_operation
    record_operation(user_id, step, status, model, duration_ms, prompt_tokens, completion_tokens, operation_id)


async def complete(messages, user_id, step, task_id=None, json_mode=False):
    config = resolve_model_config(user_id)
    if not config.configured:
        raise ModelError("尚未连接模型，请在设置 → AI 连接中添加 API。")
    started = time.perf_counter()
    from backend.agent.telemetry import start_operation
    operation_id = start_operation(user_id, step, config.model)
    try:
        content, usage = await request_completion(config, messages, json_mode=json_mode)
        if json_mode:
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                raise ModelError("模型输出未通过 JSON 格式校验，请重试。") from None
        record_trace(
            user_id,
            step,
            task_id=task_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            model=config.model,
            operation_id=operation_id,
            **usage,
        )
        return content
    except ModelError as exc:
        record_trace(
            user_id,
            step,
            "failed",
            str(exc),
            task_id,
            int((time.perf_counter() - started) * 1000),
            model=config.model,
            operation_id=operation_id,
        )
        raise


async def stream_chat(messages, user_id, step="tutor", config=None):
    config = config or resolve_model_config(user_id)
    if not config.configured:
        raise ModelError("尚未连接模型，请在设置 → AI 连接中添加 API。")
    started = time.perf_counter()
    prompt_tokens = completion_tokens = 0
    received = ended = False
    url, headers, body = request_parts(config, messages, stream=True, max_tokens=3000)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(100, connect=15)) as client:
            async with client.stream(
                "POST", url, headers=headers, json=body
            ) as response:
                check_status(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        ended = True
                        break
                    if not raw:
                        continue
                    token, usage, done = stream_event(config, json.loads(raw))
                    ended = ended or done
                    counts = usage_tokens(usage)
                    if "prompt_tokens" in usage or "input_tokens" in usage:
                        prompt_tokens = counts["prompt_tokens"]
                    if "completion_tokens" in usage or "output_tokens" in usage:
                        completion_tokens = counts["completion_tokens"]
                    if token:
                        if not isinstance(token, str):
                            raise ModelError("模型流返回了无效文本。")
                        received = True
                        yield token
        if not received or not ended:
            raise ModelError("模型未返回完整回复，请重试。")
        record_trace(
            user_id,
            step,
            duration_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=config.model,
        )
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        error = ModelError("模型流中断或服务响应无效，请重试。")
        record_trace(
            user_id,
            step,
            "failed",
            str(error),
            duration_ms=int((time.perf_counter() - started) * 1000),
            model=config.model,
        )
        raise error from None
    except ModelError as exc:
        record_trace(
            user_id,
            step,
            "failed",
            str(exc),
            duration_ms=int((time.perf_counter() - started) * 1000),
            model=config.model,
        )
        raise


async def embeddings(texts):
    settings = get_settings()
    if not settings.embedding_model:
        return None
    if not settings.embedding_key:
        raise ModelError("配置 embedding 模型后还需要可用的 EMBEDDING_API_KEY。")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                settings.embedding_base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": "Bearer " + settings.embedding_key},
                json={"model": settings.embedding_model, "input": texts},
            )
        if response.status_code >= 400:
            raise ModelError(
                f"Embedding 服务返回 HTTP {response.status_code}；资料尚未保存，请检查配置。"
            )
        items = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in items]
        if (
            len(vectors) != len(texts)
            or any(
                not isinstance(v, list)
                or not v
                or len(v) > 16000
                or any(
                    not isinstance(x, (int, float)) or not math.isfinite(x) for x in v
                )
                for v in vectors
            )
            or len({len(v) for v in vectors}) != 1
        ):
            raise ModelError("Embedding 服务未返回有效且维度一致的全部向量。")
        return vectors
    except (httpx.HTTPError, KeyError, ValueError):
        raise ModelError("Embedding 请求失败；请检查模型、服务地址和网络。") from None
