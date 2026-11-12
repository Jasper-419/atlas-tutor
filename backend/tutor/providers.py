"""Native tool calling over Atlas's existing three user-selected protocols.

Internally messages use the OpenAI chat shape. Conversion happens only at the
wire boundary; callers never parse executable instructions out of prose.
"""

import json
import time

import httpx

from backend.llm import record_trace
from backend.agent.policy import TransientModelError
from backend.model_providers import (
    ModelError,
    check_status,
    request_parts,
    usage_tokens,
)


def wire_request(config, messages, tools):
    json_mode = any(message.get("atlas_json_mode") for message in messages)
    messages = [{key: value for key, value in message.items() if key != "atlas_json_mode"} for message in messages]
    url, headers, body = request_parts(config, messages, json_mode=json_mode, stream=True, max_tokens=3200)
    if config.protocol == "anthropic-messages":
        converted = []
        for message in messages:
            role, content = message["role"], message.get("content") or ""
            if role == "system":
                continue
            if role == "tool":
                item = {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message["tool_call_id"],
                            "content": content,
                        }
                    ],
                }
            elif message.get("tool_calls"):
                blocks = [{"type": "text", "text": content}] if content else []
                blocks += [
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"]),
                    }
                    for call in message["tool_calls"]
                ]
                item = {"role": "assistant", "content": blocks}
            else:
                item = {"role": role, "content": content}
            if (
                converted
                and item["role"] == "user"
                and converted[-1]["role"] == "user"
                and isinstance(item["content"], list)
                and isinstance(converted[-1]["content"], list)
            ):
                converted[-1]["content"] += item["content"]
            else:
                converted.append(item)
        body["messages"] = converted
        if tools:
            body["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "input_schema": t["function"]["parameters"],
                }
                for t in tools
            ]
    elif config.protocol == "openai-responses":
        converted = []
        for message in messages:
            if message["role"] == "tool":
                converted.append(
                    {
                        "type": "function_call_output",
                        "call_id": message["tool_call_id"],
                        "output": message["content"],
                    }
                )
                continue
            if message.get("content"):
                converted.append(
                    {"role": message["role"], "content": message["content"]}
                )
            for call in message.get("tool_calls", []):
                converted.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                    }
                )
        body["input"] = converted
        if tools:
            body["tools"] = [{"type": "function", **t["function"]} for t in tools]
    elif tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = False
    return url, headers, body


async def model_round(config, messages, tools, user_id):
    started = time.perf_counter()
    text, calls, usage = "", {}, {}
    ended = False
    url, headers, body = wire_request(config, messages, tools)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:  # noqa: SIM117
            async with client.stream(
                "POST", url, headers=headers, json=body
            ) as response:
                if response.status_code in {429, 502, 503, 504}:
                    raise TransientModelError(
                        "模型服务暂时繁忙，请稍后重试。",
                        code="rate_limited" if response.status_code == 429 else "provider_unavailable",
                    )
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
                    data = json.loads(raw)
                    kind, delta = data.get("type", ""), ""
                    if data.get("error") or kind in {
                        "error",
                        "response.failed",
                        "response.incomplete",
                    }:
                        raise ModelError("模型工具调用流未完整完成，请重试。")
                    if config.protocol == "anthropic-messages":
                        index = data.get("index", 0)
                        if kind == "message_start":
                            usage.update(data.get("message", {}).get("usage") or {})
                        elif (
                            kind == "content_block_start"
                            and data.get("content_block", {}).get("type") == "tool_use"
                        ):
                            block = data["content_block"]
                            calls[index] = {
                                "id": block["id"],
                                "name": block["name"],
                                "arguments": "",
                            }
                        elif kind == "content_block_delta":
                            event_delta = data.get("delta", {})
                            if event_delta.get("type") == "text_delta":
                                delta = event_delta.get("text", "")
                            elif event_delta.get("type") == "input_json_delta":
                                calls[index]["arguments"] += event_delta.get(
                                    "partial_json", ""
                                )
                        elif kind == "message_delta":
                            usage.update(data.get("usage") or {})
                        ended = ended or kind == "message_stop"
                    elif config.protocol == "openai-responses":
                        if kind == "response.output_text.delta":
                            delta = data.get("delta", "")
                        if kind == "response.completed":
                            result = data.get("response", {})
                            usage = result.get("usage") or {}
                            for index, item in enumerate(result.get("output", [])):
                                if item.get("type") == "function_call":
                                    calls[index] = {
                                        "id": item["call_id"],
                                        "name": item["name"],
                                        "arguments": item["arguments"],
                                    }
                            ended = True
                    else:
                        usage.update(data.get("usage") or {})
                        choices = data.get("choices") or []
                        if choices:
                            part = choices[0]
                            if part.get("finish_reason") in {
                                "length",
                                "content_filter",
                            }:
                                raise ModelError(
                                    "模型回复被服务截断，本轮未完整完成，请缩小问题范围后重试。"
                                )
                            changes = part.get("delta") or {}
                            delta = changes.get("content") or ""
                            for call in changes.get("tool_calls") or []:
                                index = call.get("index", 0)
                                target = calls.setdefault(
                                    index, {"id": "", "name": "", "arguments": ""}
                                )
                                target["id"] += call.get("id") or ""
                                function = call.get("function") or {}
                                target["name"] += function.get("name") or ""
                                target["arguments"] += function.get("arguments") or ""
                            ended = ended or part.get("finish_reason") is not None
                    if delta:
                        if not isinstance(delta, str):
                            raise ModelError("模型返回了无效文本。")
                        text += delta
                        yield {"kind": "text", "text": delta}
                    if (
                        len(text) > 80000
                        or len(calls) > 8
                        or sum(len(c["arguments"]) for c in calls.values()) > 100000
                    ):
                        raise ModelError("模型输出超过本轮安全预算。")
        if not ended or (not text.strip() and not calls):
            raise ModelError("模型没有完整完成本轮回复。")
        normalized = []
        for call in calls.values():
            arguments = json.loads(call["arguments"] or "{}")
            if not call["id"] or not call["name"] or not isinstance(arguments, dict):
                raise ModelError("模型工具参数格式无效。")
            normalized.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
        record_trace(
            user_id,
            "tutor_agent_round",
            model=config.model,
            duration_ms=int((time.perf_counter() - started) * 1000),
            **usage_tokens(usage),
        )
        yield {
            "kind": "result",
            "message": {
                "role": "assistant",
                "content": text,
                **({"tool_calls": normalized} if normalized else {}),
            },
            "usage": usage_tokens(usage),
            "usage_known": bool(usage),
        }
    except ModelError:
        raise
    except httpx.HTTPError:
        if not text:
            raise TransientModelError("模型连接暂时中断。") from None
        raise ModelError("模型输出中断，已保留本轮过程。") from None
    except (ValueError, KeyError, TypeError, IndexError):
        raise ModelError("模型工具调用中断或响应无效，请重试。") from None
